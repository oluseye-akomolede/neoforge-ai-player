"""Script-mode tick for one bot (M2 task 3.2 wiring).

Sits in front of the planner: if a bot has a script and the runner answers,
the script's actions are what the bot does this tick. Otherwise this returns
`handled=False` and the existing L1/L3 path runs exactly as it did before.

The fallback is the whole design constraint (task 7.2: the existing planner
stays the fallback). Three things must therefore be true, and each has a test:

1. **Any failure falls through.** No script, runner down, runner silent,
   runner returns junk -- all of them return `handled=False`, never an
   exception, never an empty action list that suppresses the planner.
2. **The bound is enforced here.** `script_client.call_runner` owns the 300 ms
   bound; this module never calls the runner without it.
3. **Refused actions are visible.** A script whose actions are all refused
   must not look like a silent success -- the caller can log the refusals.

The script itself is executed by the runner service, not here. This module
feeds it a tick and binds what comes back.
"""
from __future__ import annotations

import action_binding
import snapshot as snapshot_mod
from script_client import (
    STATE_SCRIPT,
    call_runner,
)


def no_runner_detail():
    """One wording, used by both the constructor check and the tick."""
    return "no SCRIPT_RUNNER_URL configured"


def no_token_detail():
    """One wording, used by the constructor check and by the tick."""
    return ("no runner token configured (RUNNER_TOKEN unset); "
            "the runner answers 401 to every request without one")


def runner_token():
    """The bearer token the runner requires, or "" when unset.

    The runner enforces this on every contract call
    (agent-script-runner src/server.js): no `Authorization` header is a 401
    before the body is read, so a tick without it cannot succeed. Kept as its
    own function so a test can drive both branches without touching the
    environment of a live pod.
    """
    from config import RUNNER_TOKEN
    return (RUNNER_TOKEN or "").strip()


def _default_transport():
    """A `_post(path, data, timeout=...)` bound to SCRIPT_RUNNER_URL, or None.

    Returns None when the URL is unset so the caller falls through to the
    planner. That is the safe default: a pod with no runner must not POST
    anywhere, and in particular must not POST to the mod.

    The token is read here, not passed in: one place decides how a script tick
    authenticates, and `call_runner` stays transport-agnostic. A missing token
    also returns None for the same reason a missing URL does -- a runner that
    would refuse every call is not a runner, and pretending otherwise turns
    "misconfigured" into "script silently never fires".
    """
    from config import SCRIPT_RUNNER_URL
    base = (SCRIPT_RUNNER_URL or "").strip().rstrip("/")
    token = runner_token()
    if not base or not token:
        return None

    import requests

    def _post(path, data=None, timeout=5):
        r = requests.post(f"{base}{path}", json=data or {}, timeout=timeout,
                          headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status()
        return r.json()

    return _post


def _revision_of(source):
    """Stable revision id for a script body.

    The runner keys its source cache on this (§2.1), so two different scripts
    must never collide and the same script must always agree.
    """
    import hashlib
    return hashlib.sha256((source or "").encode("utf-8")).hexdigest()[:16]


class ScriptTick:
    """One bot's script-mode tick.

    `script_source` is the script text. It is sent with every tick because the
    runner is stateless between calls -- the contract has no session handle, and
    inventing one here would be a second protocol to keep in step.

    `api` is the bot's api object; `post` is the runner transport, injected so
    tests do not need a live runner.
    """

    def __init__(self, api, bot, script_source, *, post=None, cache=None,
                 game_id="minecraft", revision=None, memory=None):
        self._api = api
        self._bot = bot
        self._source = script_source
        self._game_id = game_id
        # The runner caches source by revision, so the revision must change
        # whenever the script does or a stale script keeps running. Derived
        # from the source by default rather than left to the caller.
        self._revision = revision if revision is not None else _revision_of(script_source)
        self._memory = memory
        # The per-bot snapshot cache is shared across ticks so the four-call
        # refresh is paid once per tick rather than once per evaluation.
        self._cache = cache
        self._post = post
        self.renderer = None

    @property
    def enabled(self):
        return bool(self._source)

    def tick(self):
        """Return `(handled, actions, refusals, detail)`.

        `handled=False` means "the planner should run this tick" -- the caller
        must never treat it as "do nothing".
        """
        if not self._source:
            return False, [], [], "no script"

        envelope, snap_errors = self._build_snapshot()
        # The body is the runner's §2.1 tick request, read from its handler
        # (agent-script-runner src/main.js:167-216), not invented here:
        # `game_id`, `bot_id` and `script_revision` are required strings;
        # `source` is the script (cached by revision); the script's input goes
        # under `snapshot`, NOT flattened into the tick object.
        body = {
            "game_id": self._game_id,
            "bot_id": self._bot,
            "script_revision": self._revision,
            "source": self._source,
            "snapshot": envelope,
            "memory": self._memory,
        }

        # When no transport was injected, post to SCRIPT_RUNNER_URL. It is
        # deliberately NOT `api._post`: that helper prefixes MOD_API_URL, so it
        # would send script ticks to the game mod, which answers JSON and would
        # look like a script result. No runner configured means no script mode.
        poster = self._post if self._post is not None else _default_transport()
        if poster is None:
            # Two different misconfigurations, named apart so an operator does
            # not chase a dead runner when the token is what is missing.
            from config import SCRIPT_RUNNER_URL
            if (SCRIPT_RUNNER_URL or "").strip() and not runner_token():
                return False, [], [], no_token_detail()
            return False, [], [], no_runner_detail()
        result = call_runner(self._api, body, post=poster)

        if result.state != STATE_SCRIPT:
            # Timeout, refused, error -- every non-script state falls through.
            return False, [], [], f"runner {result.state}: {result.detail}"

        bound, refusals = action_binding.bind_actions(result.actions)
        if not bound:
            # The script ran and proposed nothing bindable. That is still a
            # handled tick *if* the script genuinely said "do nothing"; but if
            # every action was refused, falling through would let the planner
            # quietly do something else, which is the opposite of what the
            # script asked. Distinguish the two.
            if refusals:
                return False, [], refusals, "all actions refused"
            return True, [], [], "script chose silence"

        return True, bound, refusals, f"{len(bound)} action(s)"

    def _build_snapshot(self):
        if self._cache is not None:
            return self._cache.get(self._bot)
        return snapshot_mod.build_state(self._api, self._bot)

    def refresh(self):
        """Force the next tick to rebuild the snapshot (after an action lands)."""
        if self._cache is not None:
            self._cache.invalidate(self._bot)

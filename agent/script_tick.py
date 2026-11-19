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

import base64

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


class RefusedRecord(Exception):
    """A runner action record that cannot be translated into a directive.

    Carries `seq` so a refusal can be matched to the script's own call, which
    is the only handle the script author has on which line was rejected.
    """

    def __init__(self, reason, seq=None):
        super().__init__(reason)
        self.reason = reason
        self.seq = seq


def translate_runner_actions(records):
    """Map the runner's action records onto `action_binding`'s input shape.

    Two shapes exist for the same thing, and this is the single place they
    meet. The runner emits `{seq, call, directive, args}` (agent-script-runner
    src/binding.js) and cardgame consumes that same record, so it is the shared
    contract; `bind_action` owns its own internal shape and its own argument
    allow-list. Teaching the binder to read `directive` is not enough and not
    right: `bind_action` walks every key and refuses any outside
    `_ALLOWED_ARGS`, so `seq`, `call` and `args` would each be refused on their
    own account. The record has to be translated, not widened.

    Returns `(pairs, refusals)` where each pair is `(bindable, seq)`. The seq is
    kept BESIDE the translated record rather than inside it: `bind_action`
    refuses any key outside its argument allow-list, so a `seq` in the dict
    would be refused, and even if admitted it would be stripped by
    `_l3_orchestrator_dispatch`'s signature filter before reaching the mod.
    The seq exists for the log, so it rides alongside -- and pairing here rather
    than in a parallel list means a later refusal cannot slide the indices out
    of step with the actions they describe.

    Refusals are collected rather than raised, matching `bind_actions`, so one
    bad record does not suppress the others. Each refusal carries `seq` and a
    reason.

    `seq` IS NOT AN INDEX, and nothing here may treat it as one. The runner
    resets it to 0 at the start of each tick and increments it on every
    *accepted host call* (`agent-script-runner/src/binding.js:116`), so a
    `say` or `send` between two `do`s consumes a number. A tick can therefore
    emit seqs `{1, 3}` or `{11, 12, 13}`, and the record at position 0 may
    carry seq 3. That is why this function returns `(bindable, seq)` pairs
    rather than zipping a list of seqs against a list of bindables: the two
    lists are different lengths and different sorts of thing, and aligning
    them by position would attach the wrong number to the wrong directive
    exactly when a call was skipped. `seq` is a label for the log line, useful
    precisely because a gap in it says a call happened that produced no
    directive.
    """
    if not isinstance(records, list):
        return [], [{"seq": None,
                     "error": f"actions must be a list, got {type(records).__name__}"}]

    pairs, refusals = [], []
    for record in records:
        try:
            pairs.append(_translate_one(record))
        except RefusedRecord as e:
            refusals.append({"seq": e.seq, "error": e.reason})
    return pairs, refusals


def _translate_one(record):
    """One record -> `(bindable, seq)`, or `RefusedRecord`.

    Anything ambiguous is refused, not guessed.
    """
    if not isinstance(record, dict):
        raise RefusedRecord(
            f"action record must be an object, got {type(record).__name__}")

    seq = record.get("seq")
    call = record.get("call")
    if call != "do":
        # The runner also queues `say` and `send` (src/binding.js), and they
        # arrive in the same list. They are legitimate records with no
        # dispatchable meaning here, so name that instead of letting
        # bind_action report a confusing missing 'kind'.
        raise RefusedRecord(
            f"action is a {call!r} call, not a dispatchable 'do': "
            f"only do-calls become directives", seq)

    directive = record.get("directive")
    if not isinstance(directive, str) or not directive.strip():
        raise RefusedRecord(
            f"'directive' must be a non-empty string, got {directive!r}", seq)

    args = record.get("args")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise RefusedRecord(
            f"'args' must be an object, got {type(args).__name__}", seq)

    for reserved in ("kind", "action"):
        if reserved in args:
            # `bind_action` reads kind/action as the action name, so an arg by
            # that name would silently become the directive and the real one
            # would be lost.
            raise RefusedRecord(
                f"args may not carry {reserved!r}: it would be read as the "
                f"action name and the directive {directive!r} would be lost", seq)

    return {"kind": directive, **args}, seq


def _number_bind_refusals(translate_refusals, bind_refusals, pairs):
    """Attach the runner's seq to each binder refusal and merge both lists.

    `bind_actions` indexes refusals by position in the list it was given, which
    is a position in `pairs` because that is what it was handed. Mapping back
    through `pairs` is what lets a bind refusal name the script's own call
    instead of an index the script author never sees.
    """
    seqs = [seq for _, seq in pairs]
    merged = list(translate_refusals)
    for refusal in bind_refusals:
        out = dict(refusal)
        idx = out.pop("index", None)
        out["seq"] = seqs[idx] if isinstance(idx, int) and 0 <= idx < len(seqs) else None
        merged.append(out)
    return merged


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


def _encode_memory(memory):
    """Put a script-memory blob into the wire form the runner expects.

    The runner base64-decodes `memory` on arrival (engine.js:1059,
    `decodeMemory`) and base64-encodes `memory_out` on the way back, so the
    blob travels encoded in both directions. Callers pass the plain str the
    script remembered; the value taken from `memory_out` is already encoded and
    is stored as-is rather than sent through here again, which is why `tick()`
    assigns `result.memory` directly.
    """
    if memory is None:
        return None
    if isinstance(memory, bytes):
        memory = memory.decode("utf-8")
    if isinstance(memory, str):
        return base64.b64encode(memory.encode("utf-8")).decode("ascii")
    raise TypeError("script memory must be str, bytes or None, got %r"
                    % type(memory).__name__)


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
        self._memory = _encode_memory(memory)
        # The per-bot snapshot cache is shared across ticks so the four-call
        # refresh is paid once per tick rather than once per evaluation.
        self._cache = cache
        self._post = post
        self.renderer = None
        # The script's own log lines from the last tick, and how many the
        # runner's cap dropped. Attributes rather than extra tuple elements:
        # `tick()` returns `(handled, actions, refusals, detail)` and widening
        # that would change every caller for data only the logging path wants.
        # Read after `tick()`; reset at the start of each tick so a caller
        # cannot re-print a previous tick's lines as if they were new.
        self.last_logs = []
        self.last_logs_dropped = 0

    @property
    def enabled(self):
        return bool(self._source)

    def tick(self):
        """Return `(handled, actions, refusals, detail)`.

        `handled=False` means "the planner should run this tick" -- the caller
        must never treat it as "do nothing".
        """
        # Cleared first: every early return below leaves the caller reading
        # these, and a previous tick's lines must never be reported as this
        # tick's. A stale log line is worse than a missing one -- it says
        # something happened that did not.
        self.last_logs = []
        self.last_logs_dropped = 0

        if not self._source:
            return False, [], [], "no script"

        envelope, snap_errors = self._build_snapshot()
        # The body is the runner's §2.1 tick request, read from its actual
        # validation (agent-script-runner src/server.js:151-164), not invented
        # here. That function is the authority and runs BEFORE routing:
        #
        #   contract_version !== 1  -> 409, for every path
        #   game_id !== token's game -> 401, wrong_game_token
        #
        # `contract_version` was missing from the first version of this body and
        # every tick was refused with a 409 that read, in this agent's log, as
        # an ordinary runner failure -- the script fired and was turned away at
        # the door, and the planner quietly took the tick. The old comment here
        # cited `src/main.js:167-216`, a file that does not do this check, which
        # is how a required field came to be absent from the request that sends
        # it. Cite the code that validates, not the code that looks related.
        body = {
            "contract_version": 1,
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

        # Hold what the script remembered. The runner returns `memory_out` as
        # BASE64 of the UTF-8 blob (contract §4.1; the encoding happens at
        # worker.js:81), and `decodeMemory` base64-decodes on the way in
        # (engine.js:1059), so it is sent back exactly as received. This was
        # write-only until M3-1b: nothing read `memory_out`, so every
        # `api.recall()` returned null in production while the test driver fed
        # the value back by hand.
        #
        # Only on a SCRIPT state: a fallback carries memory=None, and taking it
        # would wipe a good blob with an empty one on a single runner timeout.
        self._memory = result.memory

        # The script's log lines, held for the caller to print. Set on the
        # SCRIPT path only: a fallback has no script logs, and carrying the
        # previous tick's lines forward would attribute them to this one.
        self.last_logs = result.logs
        self.last_logs_dropped = result.logs_dropped

        # Two shapes meet here: the runner's and the binder's. Translate first,
        # then bind, keeping the runner's seq beside each bound action so the
        # dispatch log can carry it (M2 §8.2 evidence wants the matching seq).
        pairs, refusals = translate_runner_actions(result.actions)
        bound, bind_refusals = action_binding.bind_actions([b for b, _ in pairs])
        refusals = _number_bind_refusals(refusals, bind_refusals, pairs)
        # `bind_actions` returns `bound` in input order and names each refusal's
        # index, so the surviving seqs are the pairs whose index bind kept.
        rejected = {r["index"] for r in bind_refusals if "index" in r}
        self._last_action_seqs = [seq for i, (_, seq) in enumerate(pairs)
                                  if i not in rejected]
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
        """Return `(envelope, errors)` -- an ENVELOPE on both paths.

        The two paths used to disagree, and the one production takes was the
        wrong shape. `SnapshotCache.get` returns `(envelope, errors)`; a bare
        `build_state` returns `(state, errors)`. Unpacked at the call site as
        `envelope, snap_errors`, the uncached path therefore put a raw state
        object on the wire with no `state` key -- and the script reads
        `snapshot.state.<field>` (scout.js:65), so EVERY field it touched was
        undefined: inventory, health, position, task. Measured on TEST
        2026-11-19, Scout logged "inventory empty" every tick for eight
        minutes while holding 16 cobblestone, and the agent-side reads were
        correct the whole time. The bot was not misreporting; the envelope was
        missing.

        The agent builds `ScriptTick` with no cache (agent.py:2881), so that
        wrong path was the only one production ever ran. Wrap here rather than
        requiring a cache: the cache is an optimisation, and a shape that
        depends on whether it is present is a bug waiting for a flag change.

        `tick` and `task` are supplied the same way `SnapshotCache.get` does,
        for the same reason it documents: the envelope and the state are
        separate objects, and leaving `task=` unset makes `snapshot.task` None
        on every tick whatever the bot is doing.
        """
        if self._cache is not None:
            return self._cache.get(self._bot)
        state, errors = snapshot_mod.build_state(self._api, self._bot)
        tick = self._tick_count = getattr(self, "_tick_count", 0) + 1
        envelope = snapshot_mod.build_envelope(state, tick=tick,
                                               task=state.get("task"))
        return envelope, errors

    def refresh(self):
        """Force the next tick to rebuild the snapshot (after an action lands)."""
        if self._cache is not None:
            self._cache.invalidate(self._bot)

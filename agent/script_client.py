"""Agent-side directive dispatch for coded scripts.

The runner deliberately does NOT validate directive names: the set belongs to
the game, and the runner should not carry a copy of it (contract §4.1). So the
name is resolved here, at the moment the action is applied, on the side that
owns the set.

Two behaviours, both grounded in the mod's source rather than in a guess:

  * CASE is normalised to upper. `HttpApiServer.java:1341` already does
    `body.get("type").getAsString().toUpperCase()` before `DirectiveType.valueOf`,
    so a script naming "mine" works against this mod today. Normalising here
    makes the agent and the mod agree instead of relying on the mod's hidden
    forgiveness, and keeps the log line showing the same spelling the mod used.

  * UNKNOWN names are refused HERE. `DirectiveType.valueOf` throws
    IllegalArgumentException inside the request handler, which the agent sees as
    an HTTP 500 with no name in it. Refusing locally turns that into an error
    that names the directive and the accepted set.

    An earlier draft of M2-PLAN said a lowercase name "would reach the mod and
    fail there". That is false on this mod revision -- see the first bullet.
    A test written against that premise would have asserted a rejection that
    does not, and should not, happen.
"""

from __future__ import annotations

# The mod's DirectiveType, verified against
# src/main/java/com/sigmastrain/aiplayermod/brain/DirectiveType.java (37
# constants). Note this is NOT the skill-leaf set (35): a name can be a valid
# DirectiveType and still not be reachable via api.do, which is enforced at
# dispatch where the payload is visible. Keep this list exact; the mod is
# exact after upper-casing.
DIRECTIVE_KINDS = frozenset({
    "AREA_LOOT",
    "BREW",
    "BUILD",
    "CHANNEL",
    "COMBAT",
    "CONTAINER_PLACE",
    "CONTAINER_SEARCH",
    "CONTAINER_STORE",
    "CONTAINER_WITHDRAW",
    "CRAFT",
    "CRAFT_REQUEST",
    "CULTIVATE",
    "DISMOUNT_VEHICLE",
    "DRIVE_VEHICLE",
    "ENCHANT",
    "FARM",
    "FOLLOW",
    "FUSE_BLOCK",
    "GATHER",
    "GOTO",
    "IDLE",
    "LOCATE",
    "MANAGE_FUSION",
    "ME_STORE",
    "ME_WITHDRAW",
    "MEDITATE",
    "MINE",
    "MOUNT_VEHICLE",
    "PATROL",
    "REQUISITION",
    "SEND_ITEM",
    "SKILL",
    "SMELT",
    "STORE_ALL",
    "TELEPORT",
    "UNFUSE_BLOCK",
    "WIDE_SEARCH",
})


class UnknownDirective(ValueError):
    """A script named a directive the mod does not define."""


def normalise_directive_name(name) -> str:
    """Return the canonical UPPERCASE name, or raise UnknownDirective.

    Mirrors the mod's own `.toUpperCase()` so both sides agree, and refuses
    anything outside DIRECTIVE_KINDS rather than letting the mod throw a
    nameless 500. Surrounding whitespace is stripped first: a trailing newline
    from a script literal is a plausible typo, not a different directive.
    """
    if not isinstance(name, str):
        raise UnknownDirective(
            f"directive name must be a string, got {type(name).__name__}: {name!r}")

    canonical = name.strip().upper()
    if canonical not in DIRECTIVE_KINDS:
        raise UnknownDirective(
            f"unknown directive {name!r} (normalised {canonical!r}); "
            f"the mod defines {len(DIRECTIVE_KINDS)} directive kinds")
    return canonical


# ── Calling the runner (plan §4.3 / §4.4) ───────────────────────────────────
#
# The bound is a *stall* detector, not a *busy* detector. §1 measured the
# four-call snapshot cache refresh at median 99.4 ms and max 139.0 ms, so the
# original 100 ms sat below the observed worst case: a normally-slow tick would
# time out and fall back, which is indistinguishable from the runner being down.
# 300 ms clears the measured maximum with headroom and stays far below the 2 s
# tick cadence, so a fully timed-out script call still leaves the planner room
# to run inside the same tick.
SCRIPT_TIMEOUT = 0.3

# Runner states, as they are reported to the dashboard. "script" means the tick
# came from the runner; every other value is a fallback that a player must be
# able to see rather than infer from a motionless bot (§4.3).
STATE_SCRIPT = "script"
STATE_FALLBACK_REFUSED = "fallback_connect_refused"
STATE_FALLBACK_TIMEOUT = "fallback_timeout"
STATE_FALLBACK_ERROR = "fallback_error"

# A runner error message is model- or script-authored, so it is bounded and
# newline-escaped before it reaches a log line: a stack trace or a script that
# logs a multi-line string must not be able to forge extra log records or push
# the interesting part off the end of one.
_RUNNER_MSG_CHARS = 400


def _describe_runner_error(payload):
    """The runner's own diagnosis, for a log line. Class first, then message.

    Keeps the shape the old line had ("runner status 'error': <class>") and
    appends the message the runner always sends, so an operator reading the log
    learns what failed rather than only which bucket it fell in.
    """
    status = payload.get("status")
    err_class = payload.get("error_class")
    msg = payload.get("message")
    parts = [f"runner status {status!r}"]
    if err_class:
        parts.append(str(err_class))
    text = ": ".join(parts)
    if msg:
        text += f" — {preview_message(str(msg))}"
    return text


def preview_message(msg):
    """One bounded, newline-escaped line of a possibly-multiline message."""
    flat = msg.replace("\r", "\\r").replace("\n", "\\n")
    if len(flat) <= _RUNNER_MSG_CHARS:
        return flat
    return flat[:_RUNNER_MSG_CHARS] + f"... [+{len(flat) - _RUNNER_MSG_CHARS} chars]"


class ScriptResult:
    """Outcome of one runner call for one tick.

    ``state`` is always populated so the caller can report *why* the planner
    took over. ``actions`` is empty on any fallback, never partially filled:
    a half-applied action list is worse than none.

    ``memory`` is the opaque blob the runner returned as ``memory_out``. The
    caller must hold it and send it back on the bot's next tick, or a script's
    ``api.remember()`` is write-only: every ``api.recall()`` then returns null.
    It is None on any fallback, so a failed call cannot silently overwrite a
    good blob with an empty one.
    """

    __slots__ = ("state", "actions", "detail", "memory", "logs", "logs_dropped")

    def __init__(self, state, actions=None, detail="", memory=None, logs=None,
                 logs_dropped=0):
        self.state = state
        self.actions = actions or []
        self.detail = detail
        self.memory = memory
        # The script's own `api.log` lines, as the runner returned them
        # (src/main.js:153). They were produced and discarded until M3-1c:
        # nothing on the agent read this field, so a script's log line -- and
        # the action gate's, which motivated M3-1b -- never reached the pod
        # log. Empty on any fallback, like `actions`.
        self.logs = logs or []
        # Lines the runner's own cap dropped (binding.js:38,41). Carried so a
        # reader cannot mistake a script that logged nothing for a script whose
        # lines were dropped.
        self.logs_dropped = logs_dropped or 0

    def __repr__(self):
        return f"ScriptResult(state={self.state!r}, n_actions={len(self.actions)}, detail={self.detail!r})"


def call_runner(api, bot_state, *, post=None):
    """POST one tick to the runner and return a ScriptResult.

    The bound is sent EXPLICITLY as ``SCRIPT_TIMEOUT``. ``api._post`` defaults
    to 5 s, sized for planner calls that do real work; inheriting it here would
    let one slow runner stall a 2 s tick five times over, silently, because 5 s
    is a legal value.

    It is not a parameter, and that is deliberate (reviewer, 12:24Z). As a
    keyword default it was overridable, so a well-meant ``timeout=5`` at a call
    site -- the "pass a bigger number to be safe" edit this constant exists to
    prevent -- would have been accepted in silence, and the tests could not see
    it: they pinned the default's value, not the absence of an override. Read
    straight from the module constant it cannot be overridden by construction.

    Returns a fallback result rather than raising on every runner failure: the
    caller's job is to run the planner instead, not to handle exceptions.
    """
    import requests

    poster = post if post is not None else api._post
    try:
        payload = poster("/v1/tick", bot_state, timeout=SCRIPT_TIMEOUT)
    except requests.exceptions.ConnectTimeout as e:
        # Accepted-then-silent, or refused after the connect phase. Both are
        # treated as a stall: the bot cannot tell them apart and must not wait.
        return ScriptResult(STATE_FALLBACK_TIMEOUT, detail=f"connect timeout: {e}")
    except requests.exceptions.ReadTimeout as e:
        return ScriptResult(STATE_FALLBACK_TIMEOUT, detail=f"read timeout: {e}")
    except requests.exceptions.ConnectionError as e:
        return ScriptResult(STATE_FALLBACK_REFUSED, detail=f"connect refused: {e}")
    except Exception as e:  # noqa: BLE001 - a 5xx body, a parse error, anything
        return ScriptResult(STATE_FALLBACK_ERROR, detail=f"{type(e).__name__}: {e}")

    if not isinstance(payload, dict):
        return ScriptResult(STATE_FALLBACK_ERROR, detail=f"non-object body: {type(payload).__name__}")

    # The runner answers `status: "error"` (or `need_source`) with no actions,
    # which reads as an empty script if only `actions` is inspected. That
    # collapsed two different worlds into one: a runner that FAILED and a
    # script that deliberately chose silence. Only `ok` may count as a script
    # result; everything else falls back so the planner runs. Found while
    # wiring script_tick, by the fallback test that asserts it.
    status = payload.get("status")
    if status is not None and status != "ok":
        # The runner answers every error with a `message` beside the class
        # (agent-script-runner src/main.js:234-236), and this line used to keep
        # only the class. A failed dry tick therefore logged
        # "runner status 'error': script_error" and said nothing about WHY --
        # the 2026-11-20 21:23Z trial could not tell a missing API method from a
        # syntax error. The message is the runner's diagnosis; dropping it left
        # only the category.
        return ScriptResult(
            STATE_FALLBACK_ERROR,
            detail=_describe_runner_error(payload))

    actions = payload.get("actions")
    if actions is None:
        actions = []
    if not isinstance(actions, list):
        return ScriptResult(STATE_FALLBACK_ERROR, detail=f"actions is {type(actions).__name__}, not a list")

    # `logs` is read defensively: a runner revision that omits it, or sends a
    # non-list, must not make an otherwise good tick look like a failure. A
    # wrong-shape field is dropped rather than raised, because losing the log
    # lines is survivable and losing the tick is not.
    logs = payload.get("logs")
    if not isinstance(logs, list):
        logs = []
    dropped = payload.get("logs_dropped")
    if not isinstance(dropped, int) or isinstance(dropped, bool):
        dropped = 0

    return ScriptResult(STATE_SCRIPT, actions=actions, detail=f"{len(actions)} action(s)",
                        memory=payload.get("memory_out"), logs=logs,
                        logs_dropped=dropped)

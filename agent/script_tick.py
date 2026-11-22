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
import json

import action_binding
import snapshot as snapshot_mod
from script_client import (
    STATE_SCRIPT,
    call_runner,
)


# The tick's detail string for "the script ran but every action was refused at
# binding". Producer and consumer MUST import this rather than repeat the
# literal: the caller in agent.py carves this case out of dry-tick failure so a
# `say`-only script still binds, and a reworded literal on either side would
# kill that carve-out silently, with no error anywhere.
DETAIL_ALL_ACTIONS_REFUSED = "all actions refused"

# A script's report is capped at 2 KiB of JSON (design §3). A proposal, not a
# measurement: it is set against the largest genuinely useful report the trial
# produces, and this constant is the one place to change when it is.
RESULT_CAP_BYTES = 2048

# Marks a result that was cut. The planner MUST be able to tell "the script
# reported this much" from "the script reported exactly this" -- a truncated
# report read as complete is a report that lies about its own extent.
RESULT_TRUNCATED_MARKER = "...[truncated]"


def cap_result(value=None, *, text=None):
    """Return `(text, truncated)` -- the script's report as capped JSON text.

    A truncated result is KEPT, not dropped: a partial report the planner can
    see beats a missing one. The cap is applied to the serialised text, so it
    is about what the planner actually receives, not about the object's shape.

    Two things this deliberately does NOT do:

    - It does not deepen the cap by dropping keys. Re-serialising "everything
      except the big field" would need a rule for which field is expendable,
      and there is none -- the script decides what is worth reporting.
    - It does not truncate mid-escape and leave invalid JSON. The cut lands on
      the serialised text and the marker is appended, so the consumer is
      always reading a string it can quote, never a broken document it must
      repair.

    Pass `text=` instead of `value()` to cap a string that is ALREADY JSON --
    the runner serialises the script's report before it crosses the wire, so
    the agent holds text, not an object. Passing that text as `value` would
    serialise it a second time and turn `{"a":1}` into `"{\\"a\\":1}"`.

    Returns `(None, False)` for a value that is not reportable at all, so the
    caller can treat "no report" as its own case rather than as an empty one.
    """
    if text is None:
        if value is None:
            return None, False
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            # Not serialisable. Reported as absent rather than as a repr: a repr
            # of an unserialisable object is not what the script meant.
            return None, False
    raw = text.encode("utf-8")
    if len(raw) <= RESULT_CAP_BYTES:
        return text, False
    # The cap bounds what the PLANNER RECEIVES, marker included -- so the body
    # is cut to leave room for the marker rather than cutting to the full limit
    # and appending the marker on top of it. Cutting to RESULT_CAP_BYTES and
    # then appending returned 2062 bytes for a 2048-byte cap; nothing caught it
    # because the older tests asserted the marker and the prefix but never the
    # total length.
    room = RESULT_CAP_BYTES - len(RESULT_TRUNCATED_MARKER.encode("utf-8"))
    # errors="ignore" drops the partial character the byte cut lands on, so the
    # text stays valid UTF-8. Measured against a hand walk that backs up to the
    # boundary character by character: the two agree on every input tried
    # (2046-2048 bytes over six paddings), because both yield the longest valid
    # prefix. Simpler and the same, so this is the one that ships.
    return raw[:room].decode("utf-8", "ignore") + RESULT_TRUNCATED_MARKER, True


def result_verdict(text):
    """Whether the script's reported result says the work SUCCEEDED.

    The trigger the planner sees used to be hard-coded `"done"` whatever the
    script reported, so a script that returned `"Failed: no diamond_ore found"`
    closed its goal as DONE and the goal then never re-planned. The classifier
    is the script's OWN structured flag -- the `done` field the prompt and the
    spec already show (`api.result({done: true, ...})`) -- NOT its prose: a
    script reporting `{done: false}` must not have to avoid the word "failed"
    in a message, and a successful result is free to contain it.

    Returns True (the goal is met), False (the script reports it is still
    WORKING -- e.g. `{done: false, reason: "waiting for night"}`), or None (no
    verdict: not a JSON object, or no boolean `done`). None is NOT success --
    callers must treat "the script did not say" as distinct from "the script
    said done", so a plain-text result keeps whatever handling it had before.

    `False` is NOT a failure. It answers "is the goal met", not "did this tick
    throw"; a waiting script returns it every tick until its condition arrives.
    A real failure is a throw or a non-ok runner status, which this function
    cannot see -- that is carried separately as `result["error"]`. Conflating
    the two unbound a working script on its first tick (TEST 2026-11-22 12:28Z:
    Mystic's `{done:false,"reason":"waiting for night"}` was delivered as
    "Script result (error)" and the goal was lost).
    """
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict) or "done" not in parsed:
        return None
    done = parsed["done"]
    if not isinstance(done, bool):
        return None
    return done


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

    Returns `(pairs, refusals, deliveries)` where each pair is `(bindable, seq)`
    and each delivery is the runner's raw `say`/`send` record (see
    `validated_deliveries`, which turns it into something a caller can send).
    The seq is
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
                     "error": f"actions must be a list, got {type(records).__name__}"}], []

    pairs, refusals, deliveries = [], [], []
    for record in records:
        call = record.get("call") if isinstance(record, dict) else None
        if call in ("say", "send"):
            # Routed OUT of binding, not through it. A say is a chat call and a
            # send is an inter-bot message (M2-PLAN.md:276-280); neither is a
            # DirectiveType, so neither has a `kind` for bind_action to read.
            # Collected in script order so the caller delivers them in the
            # order the script called them.
            deliveries.append(record)
            continue
        try:
            pairs.append(_translate_one(record))
        except RefusedRecord as e:
            refusals.append({"seq": e.seq, "error": e.reason})
    return pairs, refusals, deliveries


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
        # `say` and `send` are DELIVERED, not refused, but they are not
        # bindable: they become chat calls and inter-bot messages, never a
        # directive. `translate_runner_actions` routes them out before calling
        # this, so reaching here means an unknown call kind -- refused, with
        # the kind named so the reader can tell a typo from a new action.
        raise RefusedRecord(
            f"unknown action call {call!r}: only 'do' binds to a directive "
            f"(say and send are delivered separately)", seq)

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


def validated_deliveries(deliveries):
    """Turn runner `say`/`send` records into `(deliverables, refusals)`.

    The shapes are the runner's own (agent-script-runner src/binding.js:259 and
    :271), read from the code that builds them rather than guessed:

        say  -> {seq, call: "say",  text}
        send -> {seq, call: "send", to, msg}

    Validation is repeated here even though the runner already checked these
    types (`api.say` rejects a non-string at :254, `api.send` a non-string or
    empty `otherBot` at :263). The runner version that answers may not be the
    one this agent was written against, and a malformed record must be a named
    refusal rather than a TypeError inside the caller's dispatch loop.

    `send`'s `msg` may be any JSON value (the contract carries it verbatim),
    so it is stringified for the chat path; a `to` that is not a bot id this
    agent knows is the caller's problem, not a shape error, and is passed
    through intact.

    Returns `(deliverables, refusals)`. A deliverable is
    `{"call": "say", "text": str, "seq": seq}` or
    `{"call": "send", "to": str, "text": str, "seq": seq}`.
    """
    out, refused = [], []
    for record in deliveries:
        seq = record.get("seq")
        call = record.get("call")
        if call == "say":
            text = record.get("text")
            if not isinstance(text, str):
                refused.append({"seq": seq,
                                "error": f"say 'text' must be a string, "
                                         f"got {type(text).__name__}"})
                continue
            out.append({"call": "say", "text": text, "seq": seq})
        elif call == "send":
            to = record.get("to")
            if not isinstance(to, str) or not to:
                refused.append({"seq": seq,
                                "error": "send 'to' must be a non-empty bot "
                                         "id string"})
                continue
            msg = record.get("msg")
            out.append({"call": "send", "to": to,
                        "text": "" if msg is None else _stringify_msg(msg),
                        "seq": seq})
        else:
            refused.append({"seq": seq, "error": f"unknown delivery {call!r}"})
    return out, refused


def _stringify_msg(msg):
    """The chat-path text for a `send` payload the contract allows as any JSON."""
    if isinstance(msg, str):
        return msg
    import json
    try:
        return json.dumps(msg, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(msg)


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
                 game_id="minecraft", revision=None, memory=None, dry=False):
        self._api = api
        self._bot = bot
        self._source = script_source
        self._game_id = game_id
        # M3-2 step (a): a dry tick asks the runner to evaluate against a
        # throwaway botState, so it neither reads nor spends the bot's live
        # rate windows. The agent cannot do this locally -- botState lives in
        # the runner process, one long-lived object per cached worker -- so
        # this flag on the request body IS the mechanism.
        #
        # False by default, and the field is omitted from the body entirely
        # when false: the runner tests `body.dry === true`, and every existing
        # caller must keep byte-identical behaviour (cardgame shares it).
        self._dry = dry
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
        # The `say`/`send` calls this tick delivered, for the caller to send.
        # An attribute for the same reason as last_logs: widening the tick()
        # tuple would touch every caller for data the logging path alone wants.
        self.last_deliveries = []
        # What the script reported via `api.result(v)` this tick, already JSON
        # text and already capped by the runner. None when it reported nothing.
        # An attribute for the same reason as the two above.
        self.last_result = None

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
        self.last_deliveries = []
        self.last_result = None
        self.last_task = None

        if not self._source:
            return False, [], [], "no script"

        envelope, snap_errors = self._build_snapshot()
        # The directive this tick is running, if any, so the caller can tell an
        # idle script from one waiting on its own work in flight. Read from the
        # envelope it already built: a second GET would be a different moment.
        self.last_task = envelope.get("task")
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
        # Added only when asked, never as `false`: the runner tests
        # `body.dry === true`, and a live tick's body must stay byte-identical
        # to what every existing caller sends.
        if self._dry:
            body["dry"] = True

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
        result = call_runner(self._api, body, post=poster, dry=self._dry)

        if result.state != STATE_SCRIPT:
            # Timeout, refused, error -- every non-script state falls through.
            #
            # Except one: an error tick that CARRIED a result. A script can
            # report and then throw in the same tick (runner main.js:250-255
            # sends the result on the error branch for exactly this), and that
            # report is the case the "must not be silently dropped"
            # requirement names. Hold it, marked as a failure -- the script
            # threw, so its absent `done` flag must not read as success
            # (`failed=True` travels to the trigger via last_result).
            #
            # The caller is still told `handled=False`: the tick did not
            # succeed, so the planner runs. Holding the result is about what
            # the bot LEARNED this tick, not about who acts next.
            if result.failed and result.result:
                # `text` may be None: a script that calls api.result(null) then
                # throws sends {"text": null}, which cap_result reports as
                # (None, False) -- "no report", the same case as reporting
                # nothing at all (binding.js:253-258 says the two must agree).
                # Coercing it first with str() would turn None into the string
                # "None" and hold a phantom report the planner would read as the
                # bot's own words. Only coerce a value that is actually there.
                raw_text = result.result["text"]
                text, cut = cap_result(text=None if raw_text is None else str(raw_text))
                if text is not None:
                    self.last_result = {
                        "text": text,
                        "truncated": bool(result.result.get("truncated")) or cut,
                        # No verdict is READ here: the status already said
                        # this tick failed, and consulting the payload's
                        # `done` would let a half-written result claim
                        # success over the throw that ended it.
                        "ok": False,
                        # This is the ONLY place a result is marked as an
                        # error, because it is the only path where the
                        # runtime observed a failure (the runner's status).
                        # `ok: False` alone is ambiguous: a script reporting
                        # `{done: false}` is still WORKING, and says so
                        # through the same field. Carrying the reason lets the
                        # caller deliver an error only for a real one.
                        "error": True,
                    }
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
        #
        # And only when the script actually remembered something. The runner
        # sets `memoryOut` ONLY on an `api.remember` call (binding.js:314) and
        # resets it to null at the start of every tick (binding.js:113), so a
        # successful tick that logs and returns without storing reports
        # `memory_out: null`. Assigning that cleared the STORE_ALL cooldown
        # stamp on every non-storing tick, and the next tick stored again --
        # measured on test 2026-11-19 as a dispatch every 2 ticks for 8 minutes
        # (M3-1e bug 1). The two nulls mean different things: None from a
        # fallback is "the call did not happen", null on a SCRIPT tick is "the
        # script chose not to write". Only the first may clear the blob.
        if result.memory is not None:
            self._memory = result.memory

        # The script's log lines, held for the caller to print. Set on the
        # SCRIPT path only: a fallback has no script logs, and carrying the
        # previous tick's lines forward would attribute them to this one.
        self.last_logs = result.logs
        self.last_logs_dropped = result.logs_dropped

        # What the script reported, held for the caller to hand to the planner.
        #
        # The runner already capped it and sent JSON text, so this is a HOLD,
        # not a second serialisation: cap_result() takes a Python object and
        # would quote a string that is already JSON, turning {"a":1} into
        # "{\"a\":1}". The text is re-cut against the same byte limit rather
        # than trusted, because binding.js capResult and this module must agree
        # about the limit and a silent disagreement would only ever surface as
        # an over-size string reaching the planner. Re-cutting in-range text
        # is a no-op.
        self._hold_result(result)

        # Two shapes meet here: the runner's and the binder's. Translate first,
        # then bind, keeping the runner's seq beside each bound action so the
        # dispatch log can carry it (M2 §8.2 evidence wants the matching seq).
        pairs, refusals, raw_deliveries = translate_runner_actions(result.actions)
        bound, bind_refusals = action_binding.bind_actions([b for b, _ in pairs])
        refusals = _number_bind_refusals(refusals, bind_refusals, pairs)
        # `say`/`send` are delivered, not bound. They are collected on the
        # instance for the caller rather than returned in the tuple: the tuple
        # is `(handled, actions, refusals, detail)` and widening it would touch
        # every caller for data only the dispatch path wants -- the same reason
        # last_logs is an attribute. A DRY tick collects NONE: its whole point
        # is that it carries no side effects, and a chat line or an inter-bot
        # message is the most visible side effect there is.
        if self._dry:
            self.last_deliveries = []
        else:
            self.last_deliveries, delivery_refusals = validated_deliveries(
                raw_deliveries)
            refusals = refusals + delivery_refusals
        # `bind_actions` returns `bound` in input order and names each refusal's
        # index, so the surviving seqs are the pairs whose index bind kept.
        rejected = {r["index"] for r in bind_refusals if "index" in r}
        self._last_action_seqs = [seq for i, (_, seq) in enumerate(pairs)
                                  if i not in rejected]
        if not bound and not self.last_deliveries:
            # The script ran and proposed nothing this agent can DO. That is
            # still a handled tick *if* the script genuinely said "do nothing";
            # but if every action was refused, falling through would let the
            # planner quietly do something else, which is the opposite of what
            # the script asked. Distinguish the two. A tick that only said
            # something is NOT this case: it has deliveries, and the trial of
            # 2026-11-20 22:21Z is what happens when a say-only script is read
            # as "all actions refused" -- the bot falls back to the planner and
            # never speaks.
            if refusals:
                return False, [], refusals, DETAIL_ALL_ACTIONS_REFUSED
            return True, [], [], "script chose silence"

        if not bound:
            return True, [], refusals, (
                f"{len(self.last_deliveries)} delivery(ies)")
        if self.last_deliveries:
            return True, bound, refusals, (
                f"{len(bound)} action(s), "
                f"{len(self.last_deliveries)} delivery(ies)")
        return True, bound, refusals, f"{len(bound)} action(s)"

    def _hold_result(self, result):
        """Keep what the script reported, for the caller to hand to the planner.

        The runner sends the report already serialised as JSON text and already
        capped, so this is a HOLD and not a second serialisation -- passing the
        text as a *value* to cap_result() would serialise it twice and turn
        {"a":1} into the string "{\\"a\\":1}".

        The text is nonetheless re-cut against the same byte limit rather than
        trusted: binding.js capResult and cap_result() here must agree about the
        limit, and a silent disagreement would only ever show up as an over-size
        string reaching the planner. Re-cutting in-range text is a no-op.
        """
        reported = result.result
        if not (reported and reported.get("text") is not None):
            return
        text, cut = cap_result(text=str(reported["text"]))
        if text is not None:
            self.last_result = {"text": text,
                                "truncated": bool(reported.get("truncated")) or cut,
                                "ok": result_verdict(text)}

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

"""Read-only per-tick snapshot for the script path (M2 task 3.1).

Builds contract v1 §3's envelope from data the agent already fetches. Nothing
here writes to the mod: the only calls are reads (`status`, `inventory`,
`blocks`, `entities`, `get_directive`), so a script cannot reach world state
through the snapshot at all.

"Read-only" is enforced by construction rather than by a guard: there is no
write path to check, because the module makes no writing calls. The tests assert
that against the api surface actually invoked, not against this file's text --
the `IDLE` subject was ruled out on exactly this ground (a behaviour with zero
observables), so the claim is pinned to the same standard.

Two properties this module exists to guarantee, and both are load-bearing:

1. **The script gets a copy, never a reference.** `json.dumps` at the boundary
   is the read-only guarantee: the script receives bytes it may mutate freely,
   and those mutations are decoded into fresh objects the mod never sees. The
   runner deep-freezes it again, but that is defence in depth, not the guard.

2. **The refresh is cached per tick, not per script evaluation.** Measured on
   TEST, a four-call refresh is median 99.4 ms / max 139 ms (M2-PLAN §1); the
   planner cadence is 2 s. Paying that once per tick rather than once per
   evaluation is what keeps it off the critical path, and it is why the bound is
   300 ms rather than 100 ms -- the bound stops a *stalled* runner, it is not a
   budget for a healthy one.

Standard library only, plus the agent's own `api` module, which is passed in
rather than imported so this file stays testable without the agent's deps.
"""
from __future__ import annotations

import json
import time

# Fields the runner treats as opaque; the binding is what goes in `state`.
# Kept flat and JSON-native (no dataclasses, no datetimes) so `json.dumps` is
# the only serialisation step and nothing can smuggle a live object through.
_EMPTY_STATE = {
    "health": None,
    "food": None,
    "position": None,
    "inventory": [],
    "nearby": {"blocks": [], "mobs": []},
    "task": None,
}

# Sentinel: distinguishes "the fetch itself failed" (already recorded by
# _read) from "the fetch returned something we cannot read".
_UNREAD = object()


def _shape(value):
    """Name a value's shape for an error entry without dumping the value."""
    return type(value).__name__


def build_state(api, bot, *, block_radius=8, entity_radius=24.0):
    """Fetch the four reads and assemble contract §3's MINECRAFT `state`.

    Returns `(state, errors)` where `errors` records which reads failed, so the
    caller can surface a degraded snapshot instead of a silently empty one.
    """
    errors = []

    def _read(name, fn, default):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            errors.append({"reader": name, "error": type(e).__name__})
            return default

    def _obs(name, fn, key):
        """Read one observation and unwrap the game's one-key envelope.

        Every observation endpoint on the mod side answers with a wrapper, not
        the list a script wants:

            /bot/<bot>/blocks    -> {"blocks":    [...]}  (HttpApiServer:505)
            /bot/<bot>/entities  -> {"entities":  [...]}  (HttpApiServer:504)
            /bot/<bot>/inventory -> {"inventory": [...]}  (HttpApiServer:469)

        Storing that wrapper unchanged is what made `look` answer
        `matches: []` on a bot standing in front of iron ore: the runner
        requires an Array and got an Object, and said so only by finding
        nothing. So the contract here is a LIST, and this is where it is
        produced.

        A bare list is accepted too, so a reader that one day answers with the
        list directly does not become silently empty. Anything else is a reader
        error: it goes in `errors` rather than turning into an empty list that
        says "the world is empty" when the truth is "I could not read it".
        """
        raw = _read(name, fn, _UNREAD)
        if raw is _UNREAD:
            return []          # _read already recorded the fetch failure
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            inner = raw.get(key)
            if isinstance(inner, list):
                return inner
            errors.append({"reader": name, "error": "wrapped-value-not-a-list",
                           "got": _shape(inner)})
            return []
        errors.append({"reader": name, "error": "unexpected-shape", "got": _shape(raw)})
        return []

    status = _read("status", lambda: api.status(bot), {}) or {}
    directive = _read("directive", lambda: api.get_directive(bot), None)

    # The world clock, from the bot's own level. `None` when the mod does not
    # send it -- an older mod, or a status the reader failed -- and NEVER a
    # derived value: the whole reason this field exists is that a script invented
    # `(6000 + ticks*10) % 12000` and announced night at noon (prod Mystic,
    # 2026-11-22). A script that needs a time and finds None must say it cannot
    # tell, not make one up; the planner prompt carries that rule.
    world = {
        "day_time": status.get("day_time"),
        "is_night": status.get("is_night"),
    }

    return {
        "health": status.get("health"),
        "food": status.get("food"),
        "position": status.get("position"),
        "world": world,
        "inventory": _obs("inventory", lambda: api.inventory(bot), "inventory"),
        "nearby": {
            "blocks": _obs("blocks", lambda: api.blocks(bot, block_radius), "blocks"),
            "mobs": _obs("entities", lambda: api.entities(bot, entity_radius), "entities"),
        },
        # The WHOLE GET /directive body, not the bare `directive` map inside it.
        # The mod answers that route with BotBrain.toMap (HttpApiServer.java:1338):
        # `directive` (Directive.toMap: id/type/status/x/y/z) plus `progress`,
        # which is where a behaviour's result lives. Taking only the inner map
        # made `progress.result` -- and therefore a GOTO's arrived_at -- a field
        # no script could read. The directive stays reachable (its id and status
        # tell a script WHICH directive finished) at state.task.directive.
        "task": directive,
    }, errors


def build_envelope(state, *, tick, events=None, task=None):
    """Wrap a `state` in contract §3's shared envelope.

    `events` are the outcomes of earlier actions, delivered by the game on the
    following tick (contract §3); they are mirrored from the directive's own
    reported outcome rather than invented here.

    `task` is passed through as the directive the agent is currently running,
    unchanged. It was previously re-wrapped as `{"goal": goal}` under a keyword
    named `goal` -- which meant the caller's task, whatever shape it had, was
    silently replaced by a dict keyed on a field the task does not have. The
    contract does not define `task`'s shape (a known gap), so this module must
    not invent one: pass it through and let the contract settle it.
    """
    return {
        "tick": int(tick),
        "server_ms": int(time.time() * 1000),
        "state": state,
        "events": list(events or []),
        "task": task,
    }


def freeze(envelope):
    """The read-only boundary: serialise, so the script gets bytes it cannot
    write back through. Returns the JSON text, not a dict."""
    return json.dumps(envelope, separators=(",", ":"))


class SnapshotCache:
    """Per-tick cache of the assembled snapshot, one entry per bot.

    TTL is the planner cadence (`TICK_DELAY`), which is why the cache is the
    right place for the cost: the four-call refresh is paid once per tick and
    every script evaluation inside that tick reuses it. Passing `ttl=0` disables
    caching, which the tests use to prove the refresh actually happens.
    """

    def __init__(self, api, *, ttl, clock=time.monotonic):
        self._api = api
        self._ttl = float(ttl)
        self._clock = clock
        self._entries = {}  # bot -> (expires_at, envelope, errors)
        self._tick = {}     # bot -> last tick number handed out

    def get(self, bot, *, block_radius=8, entity_radius=24.0):
        """Return `(envelope, errors)`, refreshing if the entry has expired."""
        now = self._clock()
        hit = self._entries.get(bot)
        if hit is not None and now < hit[0]:
            return hit[1], hit[2]

        state, errors = build_state(
            self._api, bot, block_radius=block_radius, entity_radius=entity_radius
        )
        tick = self._tick.get(bot, 0) + 1
        self._tick[bot] = tick
        # `task` must be passed explicitly. build_state reads the running
        # directive via api.get_directive into state["task"], but the envelope
        # and the state are separate objects: calling build_envelope without
        # `task=` leaves envelope["task"] at its None default on EVERY tick,
        # whatever the bot is doing. That is not a rare shape, it is the only
        # shape this cache can produce - so any script guarding on
        # `snapshot.task` had a dead first branch.
        envelope = build_envelope(state, tick=tick, task=state.get("task"))
        self._entries[bot] = (now + self._ttl, envelope, errors)
        return envelope, errors

    def invalidate(self, bot=None):
        """Drop one bot's entry, or all of them.

        Called when the caller knows the world moved in a way the TTL will not
        cover -- after an action is applied, so tick `n+1` does not report a
        state from before the action ran.

        Only the entry is dropped, not the tick counter: a forced refresh means
        "fetch again", not "this is a new turn". Resetting the counter here made
        invalidate() rewind the clock protocol, and a second envelope could then
        reuse an earlier tick number.
        """
        if bot is None:
            self._entries.clear()
        else:
            self._entries.pop(bot, None)

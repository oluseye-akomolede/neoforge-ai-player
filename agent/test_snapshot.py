"""Tests for agent/snapshot.py — M2 task 3.1, the read-only snapshot.

Loaded by path for the same reason as test_script_client.py: `agent/` has no
__init__.py, so `from agent.snapshot import ...` would execute agent.py and drag
in psycopg2 and uvicorn, and the test would stop being runnable where it matters.

The test that justifies this file is `SnapshotIsReadOnlyTest`. Contract v1 §3
says the runner deep-freezes the snapshot before the script sees it; that is
defence in depth, and this suite must not rely on it. The guarantee the agent
owes is that the script holds bytes, not a live reference into the mod's data.
"""

import importlib.util
import json
import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "snapshot_under_test", os.path.join(_HERE, "snapshot.py")
)
_snap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_snap)

SnapshotCache = _snap.SnapshotCache
build_envelope = _snap.build_envelope
build_state = _snap.build_state
freeze = _snap.freeze


class _FakeApi:
    """A stand-in mod that records every call it receives."""

    def __init__(self, fail=()):
        self.calls = []
        self._fail = set(fail)

    def _maybe_fail(self, name):
        if name in self._fail:
            raise RuntimeError(f"{name} is down")

    def status(self, bot):
        self.calls.append(("status", bot))
        self._maybe_fail("status")
        # Bot-dependent, like the real mod: a fixture that returns the same
        # values for every bot makes "the caches are separate" unfalsifiable.
        return {"health": 20.0, "food": 18,
                "position": {"x": float(len(bot)), "y": 64.0, "z": -3.0,
                             "dim": "minecraft:overworld"}}

    # NOTE the wrappers. Every observation endpoint answers with a one-key
    # object, not a bare list -- the fake used to return the list directly and
    # that is exactly why the live scripts came up empty while this suite was
    # green. Read at source, not from a fixture:
    #   HttpApiServer.java:469  Map.of("inventory", bot.getCachedInventory())
    #   HttpApiServer.java:504  Map.of("entities",  bot.getCachedEntities())
    #   HttpApiServer.java:505  Map.of("blocks",    bot.getCachedBlocks())
    def inventory(self, bot):
        self.calls.append(("inventory", bot))
        self._maybe_fail("inventory")
        return {"inventory": [{"item": "minecraft:stone", "count": 3}]}

    def blocks(self, bot, radius=8):
        self.calls.append(("blocks", bot, radius))
        self._maybe_fail("blocks")
        # Copied from NearbyBlockIndex.select's real output, not invented: the
        # mod has never sent `type` on a block. These are the fields a script
        # actually receives (BotPlayer.java getNearbyBlocks -> CacheEntry).
        return {"blocks": [{"id": "minecraft:chest",
                            "block": "minecraft:chest",
                            "position": {"x": 2, "y": 64, "z": -3}}]}

    def entities(self, bot, radius=24.0):
        self.calls.append(("entities", bot, radius))
        self._maybe_fail("entities")
        # Entities DO carry `type` (BotPlayer.java:883) -- unlike blocks. Real
        # shape: distance is a String, formatted "%.1f", because that is what
        # the mod puts on the wire (BotPlayer.java:886).
        return {"entities": [{"type": "minecraft:cow",
                              "name": "Cow",
                              "position": {"x": 5.0, "y": 64.0, "z": 1.5},
                              "distance": "4.2",
                              "health": 10.0}]}

    def get_directive(self, bot):
        self.calls.append(("directive", bot))
        self._maybe_fail("directive")
        return {"type": "STORE_ALL", "status": "running"}


class BuildStateTest(unittest.TestCase):

    def test_all_five_readers_are_called(self):
        api = _FakeApi()
        state, errors = build_state(api, "Scout")
        self.assertEqual(errors, [])
        self.assertEqual(
            [c[0] for c in api.calls],
            ["status", "directive", "inventory", "blocks", "entities"])

    def test_state_carries_the_contract_fields(self):
        state, _ = build_state(_FakeApi(), "Scout")
        for field in ("health", "food", "position", "inventory", "nearby", "task"):
            self.assertIn(field, state)
        self.assertEqual(state["health"], 20.0)
        # Blocks carry {id, block, position} -- no `type`, and NOT an empty
        # `type` key either. Pinning the exact key set is the point: an
        # invented `type` is what let this fixture drift from the mod.
        self.assertEqual(sorted(state["nearby"]["blocks"][0]),
                         ["block", "id", "position"])
        self.assertEqual(state["nearby"]["blocks"][0]["id"], "minecraft:chest")
        self.assertEqual(state["nearby"]["mobs"][0]["type"], "minecraft:cow")
        self.assertEqual(state["nearby"]["mobs"][0]["distance"], "4.2")

    def test_one_dead_reader_degrades_that_field_only(self):
        # A mod endpoint being down must not blank the snapshot: the script can
        # still act on position and inventory. And the failure is named, so a
        # degraded snapshot never looks like a normal empty one.
        state, errors = build_state(_FakeApi(fail={"inventory"}), "Scout")
        self.assertEqual(state["inventory"], [])
        self.assertEqual(state["health"], 20.0)
        self.assertEqual(errors, [{"reader": "inventory", "error": "RuntimeError"}])

    # ── The game's wrapper is unwrapped here, once ──────────────────────────
    # b9edb63: live, state.nearby.blocks held {"blocks": [...]} unchanged, so
    # `look` -- which requires an Array -- answered ok:true, matches:[] while
    # the bot stood in front of iron ore. The next four tests fail if the
    # wrapper ever reaches the script again.

    def test_the_games_wrapped_response_becomes_a_list(self):
        # Shape taken from HttpApiServer.java:469/504/505, not hand-written.
        state, errors = build_state(_FakeApi(), "Scout")
        self.assertEqual(errors, [])
        for value in (state["inventory"],
                      state["nearby"]["blocks"],
                      state["nearby"]["mobs"]):
            self.assertIsInstance(value, list)
        self.assertEqual(state["nearby"]["blocks"][0]["id"], "minecraft:chest")
        self.assertEqual(state["nearby"]["mobs"][0]["type"], "minecraft:cow")

    def test_a_bare_list_is_tolerated(self):
        # A reader that answers with the list directly must not become
        # silently empty -- that is the same failure one layer along.
        api = _FakeApi()
        api.blocks = lambda bot, radius=8: [{"id": "minecraft:iron_ore"}]
        state, errors = build_state(api, "Scout")
        self.assertEqual(errors, [])
        self.assertEqual(state["nearby"]["blocks"], [{"id": "minecraft:iron_ore"}])

    def test_an_unusable_shape_is_a_reader_error_not_silence(self):
        # An empty list must never be the way an unreadable world is reported:
        # that is indistinguishable from "there is nothing here".
        api = _FakeApi()
        api.blocks = lambda bot, radius=8: {"blocks": "not-a-list"}
        state, errors = build_state(api, "Scout")
        self.assertEqual(state["nearby"]["blocks"], [])
        self.assertEqual(
            [e["reader"] for e in errors], ["blocks"],
            "an unusable block shape was reported as an empty world")
        self.assertTrue(errors[0]["error"])

    def test_the_wrapper_is_unwrapped_once_for_every_reader(self):
        # inventory had the identical defect and was not in the original row:
        # look.inventory() would have returned items: [] on a bot holding shears.
        api = _FakeApi()
        api.inventory = lambda bot: {"inventory": [{"item": "minecraft:shears", "count": 1}]}
        state, _ = build_state(api, "Scout")
        self.assertEqual(state["inventory"], [{"item": "minecraft:shears", "count": 1}])

    def test_every_reader_failing_is_still_a_snapshot(self):
        state, errors = build_state(
            _FakeApi(fail={"status", "inventory", "blocks", "entities", "directive"}),
            "Scout")
        self.assertEqual(len(errors), 5)
        json.dumps(state)  # still serialisable, which is what the script needs


class SnapshotIsReadOnlyTest(unittest.TestCase):
    """The guarantee: the script gets bytes, not a reference into the mod."""

    def test_mutating_the_frozen_snapshot_cannot_reach_the_source(self):
        api = _FakeApi()
        state, _ = build_state(api, "Scout")
        before = json.loads(json.dumps(state))  # the state as it was

        text = freeze(build_envelope(state, tick=1))
        # What a script does: decode, mutate freely.
        decoded = json.loads(text)
        decoded["state"]["health"] = -1
        decoded["state"]["inventory"].clear()
        decoded["state"]["nearby"]["blocks"].append(
            {"id": "planted", "block": "planted", "position": {"x": 0, "y": 0, "z": 0}})

        self.assertEqual(json.dumps(state, sort_keys=True),
                         json.dumps(before, sort_keys=True),
                         "mutating the script's copy reached the agent's object")
        # And a second decode of the same envelope is unaffected.
        self.assertEqual(json.loads(text)["state"]["health"], 20.0)

    def test_freeze_returns_text_not_a_dict(self):
        # If this ever returns a dict, the boundary is gone and the read-only
        # claim rests entirely on the runner's freeze -- which is not ours.
        out = freeze(build_envelope({"health": 20.0}, tick=1))
        self.assertIsInstance(out, str)

    def test_the_snapshot_uses_no_writing_calls(self):
        # 3.1 is read-only in the strongest sense: there is no write path to
        # guard, because the builder only ever calls readers. Asserted against
        # the api surface actually invoked, not against the module's text.
        api = _FakeApi()
        build_state(api, "Scout")
        readers = {"status", "inventory", "blocks", "entities", "directive"}
        self.assertTrue({c[0] for c in api.calls} <= readers,
                        f"build_state called a non-reader: "
                        f"{ {c[0] for c in api.calls} - readers }")


class EnvelopeTest(unittest.TestCase):

    def test_envelope_matches_contract_three(self):
        env = build_envelope({"health": 20.0}, tick=7, task={"type": "STORE_ALL"})
        for field in ("tick", "server_ms", "state", "events", "task"):
            self.assertIn(field, env)
        self.assertEqual(env["tick"], 7)
        self.assertEqual(env["events"], [])
        # Passed through unchanged. The earlier version re-wrapped this as
        # {"goal": ...}, replacing the caller's task with a dict keyed on a
        # field a task does not have -- and the old test asserted the rewrap,
        # so it passed on the defect.
        self.assertEqual(env["task"], {"type": "STORE_ALL"})

    def test_task_is_not_reshaped(self):
        # The control for the test above: any non-None shape must survive
        # verbatim, so a future re-wrap fails here rather than silently
        # returning a plausible-looking dict.
        for task in ({"type": "MINE"}, {}, {"goal": "store", "extra": 1}):
            self.assertEqual(build_envelope({}, tick=1, task=task)["task"], task)

    def test_events_are_carried_through_unchanged(self):
        events = [{"type": "directive_result", "data": {"ok": True}}]
        env = build_envelope({}, tick=1, events=events)
        self.assertEqual(env["events"], events)

    def test_tick_is_an_int_for_the_runner(self):
        env = build_envelope({}, tick="12")
        self.assertIsInstance(env["tick"], int)

    def test_the_world_is_reachable_at_exactly_one_path(self):
        # The runner reads the world at snapshot.state.nearby, written once in
        # look.js's __lookWorld. If the envelope ever also grew a TOP-LEVEL
        # nearby, the runner's tolerant-resolver mutant would become correct by
        # accident and no behavioural test could tell -- both paths would carry
        # the same data. Pin the envelope's shape: the world lives in state,
        # and the top level carries no second copy. This is the producer half
        # of the 2026-11-21 idle-scripts defect.
        env = build_envelope({"health": 20.0, "nearby": {"blocks": [1], "mobs": []}}, tick=1)
        self.assertNotIn("nearby", env, "the envelope must not carry a second, top-level world path")
        self.assertIn("nearby", env["state"], "the world must stay where the runner reads it")


class SnapshotCacheTest(unittest.TestCase):

    def test_refresh_is_paid_once_per_tick_not_per_evaluation(self):
        # M2-PLAN §1: a four-call refresh is median 99.4 ms / max 139 ms
        # against a 2 s cadence. Caching per tick is what keeps that off the
        # critical path; five evaluations inside one tick must pay it once.
        now = [1000.0]
        cache = SnapshotCache(_FakeApi(), ttl=2.0, clock=lambda: now[0])
        api = cache._api

        for _ in range(5):
            cache.get("Scout")
        self.assertEqual(len(api.calls), 5, "one refresh, five calls, five evaluations")

    def test_an_expired_entry_refreshes(self):
        now = [1000.0]
        cache = SnapshotCache(_FakeApi(), ttl=2.0, clock=lambda: now[0])
        api = cache._api

        cache.get("Scout")
        now[0] += 2.5  # past the TTL
        cache.get("Scout")
        self.assertEqual(len(api.calls), 10, "the second call should have refreshed")

    def test_bots_do_not_share_a_cache_entry(self):
        cache = SnapshotCache(_FakeApi(), ttl=2.0, clock=lambda: 1000.0)
        # "Scout" and "Miner" are both five characters, and len was my first
        # bot-dependent fixture -- so the two bots were indistinguishable and
        # this assertion could not fire. Caught by the control below, which is
        # the only reason it is visible.
        scout = cache.get("Scout")[0]
        miner = cache.get("MinerTwo")[0]
        # Compared on the bot-derived field, not the whole envelope: server_ms
        # can differ between the two calls for a reason unrelated to caching,
        # which would make this pass while the entries were shared.
        self.assertNotEqual(scout["state"]["position"], miner["state"]["position"])
        self.assertEqual(len(cache._api.calls), 10)

    def test_a_shared_cache_entry_would_be_caught(self):
        # Positive control for the test above: if the cache keyed on nothing,
        # both bots would get the first bot's position and the assertion would
        # fire. Proves the fixture can distinguish them at all.
        cache = SnapshotCache(_FakeApi(), ttl=2.0, clock=lambda: 1000.0)
        scout = cache.get("Scout")[0]
        same_key = cache.get("Scout")[0]
        self.assertEqual(scout["state"]["position"], same_key["state"]["position"],
                         "same bot must reuse its own entry")

    def test_tick_increases_across_refreshes(self):
        now = [1000.0]
        cache = SnapshotCache(_FakeApi(), ttl=1.0, clock=lambda: now[0])
        first, _ = cache.get("Scout")
        now[0] += 1.5
        second, _ = cache.get("Scout")
        self.assertEqual(second["tick"], first["tick"] + 1)

    def test_invalidate_forces_a_refresh_for_that_bot_only(self):
        cache = SnapshotCache(_FakeApi(), ttl=60.0, clock=lambda: 1000.0)
        cache.get("Scout")
        cache.get("Miner")
        cache.invalidate("Scout")
        cache.get("Scout")
        cache.get("Miner")
        # 5 + 5 for the initial pair, plus 5 for Scout's forced refresh.
        self.assertEqual(len(cache._api.calls), 15)

    def test_invalidate_does_not_rewind_the_tick_number(self):
        # A forced refresh means "fetch again", not "this is a new turn".
        # Clearing the counter made invalidate() rewind the tick protocol, so
        # two different snapshots could both claim tick 1.
        cache = SnapshotCache(_FakeApi(), ttl=60.0, clock=lambda: 1000.0)
        first = cache.get("Scout")[0]
        cache.invalidate("Scout")
        second = cache.get("Scout")[0]
        self.assertEqual(second["tick"], first["tick"] + 1,
                         "invalidate rewound the tick counter")

    def test_envelope_from_the_cache_carries_the_running_task(self):
        # Built THROUGH SnapshotCache, not through build_envelope with a
        # hand-passed task=. That distinction is the whole test: the earlier
        # EnvelopeTest called build_envelope(task={...}) and passed, while
        # production called build_envelope(state, tick=tick) - no task - so
        # envelope["task"] was None on every tick and scout.js's first guard
        # (if (snapshot.task) return []) could never fire. The fixture agreed
        # with the reader instead of with the producer.
        cache = SnapshotCache(_FakeApi(), ttl=60.0, clock=lambda: 1000.0)
        envelope = cache.get("Scout")[0]
        self.assertIsNotNone(
            envelope["task"],
            "envelope['task'] is None while the bot has a directive running - "
            "the script's in-flight guard is dead")
        self.assertEqual(envelope["task"].get("type"), "STORE_ALL")

    def test_envelope_task_is_none_when_nothing_is_running(self):
        # The control. A fixture that always reports a directive would let a
        # hardcoded task pass; an idle bot must yield None so the guard's
        # two branches stay distinguishable.
        class _IdleApi(_FakeApi):
            def get_directive(self, bot):
                self.calls.append(("directive", bot))
                return None

        cache = SnapshotCache(_IdleApi(), ttl=60.0, clock=lambda: 1000.0)
        self.assertIsNone(cache.get("Scout")[0]["task"])

    def test_ttl_zero_disables_caching(self):
        cache = SnapshotCache(_FakeApi(), ttl=0.0, clock=lambda: 1000.0)
        cache.get("Scout")
        cache.get("Scout")
        self.assertEqual(len(cache._api.calls), 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)

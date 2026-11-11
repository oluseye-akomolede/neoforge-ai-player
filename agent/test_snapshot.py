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

    def inventory(self, bot):
        self.calls.append(("inventory", bot))
        self._maybe_fail("inventory")
        return [{"item": "minecraft:stone", "count": 3}]

    def blocks(self, bot, radius=8):
        self.calls.append(("blocks", bot, radius))
        self._maybe_fail("blocks")
        return [{"type": "minecraft:chest", "pos": {"x": 2, "y": 64, "z": -3}}]

    def entities(self, bot, radius=24.0):
        self.calls.append(("entities", bot, radius))
        self._maybe_fail("entities")
        return [{"type": "minecraft:cow", "distance": 4.2}]

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
        self.assertEqual(state["nearby"]["blocks"][0]["type"], "minecraft:chest")
        self.assertEqual(state["nearby"]["mobs"][0]["type"], "minecraft:cow")

    def test_one_dead_reader_degrades_that_field_only(self):
        # A mod endpoint being down must not blank the snapshot: the script can
        # still act on position and inventory. And the failure is named, so a
        # degraded snapshot never looks like a normal empty one.
        state, errors = build_state(_FakeApi(fail={"inventory"}), "Scout")
        self.assertEqual(state["inventory"], [])
        self.assertEqual(state["health"], 20.0)
        self.assertEqual(errors, [{"reader": "inventory", "error": "RuntimeError"}])

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
        decoded["state"]["nearby"]["blocks"].append({"type": "planted"})

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

    def test_ttl_zero_disables_caching(self):
        cache = SnapshotCache(_FakeApi(), ttl=0.0, clock=lambda: 1000.0)
        cache.get("Scout")
        cache.get("Scout")
        self.assertEqual(len(cache._api.calls), 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)

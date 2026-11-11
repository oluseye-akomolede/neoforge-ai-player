"""Tests for agent/scripts/scout.js — the M2 first script (8.2).

Node-driven: scout.js is the artefact under test, so it is read from disk and
evaluated with stub `api` / `snapshot` globals exactly as the runner would
provide them. Nothing here re-implements the script's logic; every assertion is
against what the committed .js returns.

The load-bearing assertion is `test_returns_exactly_the_parity_directive`. 8.2
compares the script path's POST body against the planner path's, and that
comparison is only worth anything if the SCRIPT supplies the directive. If this
test pinned the expectation loosely (a kind, or a non-empty list), a script that
later returned nothing would still pass while 8.2 compared two empty bodies --
the harness-writes-both-sides defect the reviewer named. So the whole return
value is pinned, not a field of it.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest

# This file lives in agent/, and scout.js in agent/scripts/, so _HERE is already
# the directory to join from. The first version took dirname(_HERE) as well and
# resolved one level too high -- it only failed because unittest was invoked
# from inside agent/ and `__file__` happened to be relative then. Absolute
# __file__ makes the off-by-one visible; the arithmetic is what was wrong.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPT = os.path.join(_HERE, "scripts", "scout.js")

# The runner's real surface (agent-script-runner/src/engine.js #installApi).
_API_VERBS = ("do", "say", "send", "remember", "recall", "log")


def _run(snapshot_literal: str) -> dict:
    """Evaluate scout.js with stub globals; return {"actions", "logs"}."""
    src = open(_SCRIPT, encoding="utf-8").read()
    # scout.js ends with a bare `tick();`. Rewrite only that final invocation so
    # the body under test is otherwise the committed bytes.
    body = src.replace("\ntick();", "\n;return tick();")
    assert body != src, "scout.js no longer ends with a bare tick(); update this test"

    harness = f"""
const fs = require("fs");
const body = {json.dumps(body)};
const logs = [];
const api = {{ {", ".join(f'{v}: (...a) => logs.push(a.join(" "))' for v in _API_VERBS)} }};
api.do = () => ({{}});
const snapshot = {snapshot_literal};
const fn = new Function("api", "snapshot", body);
console.log(JSON.stringify({{ actions: fn(api, snapshot), logs }}));
"""
    out = subprocess.run(
        ["node", "-e", harness], capture_output=True, text=True, timeout=30,
    )
    if out.returncode != 0:
        raise AssertionError(f"node failed: {out.stderr.strip()}")
    return json.loads(out.stdout)


def _envelope(health=20.0, task=None, **extra):
    """A snapshot in the shape SnapshotCache.get actually produces.

    The flat {"health": ...} literals these tests used to pass are the shape
    scout.js WANTS; production sends {tick,server_ms,state,events,task} with
    the bot facts under `state`. Tests written against the wished-for shape are
    what let a dead guard pass three green suites, so this builds the real one
    by default. test_guards_fire_on_the_envelope_the_cache_actually_produces
    goes further and builds it through the cache itself.
    """
    env = {"tick": 1, "server_ms": 1700000000000, "events": [],
           "state": {"health": health, "food": 18,
                     "position": {"x": 0.0, "y": 64.0, "z": 0.0,
                                  "dim": "minecraft:overworld"},
                     "inventory": [], "nearby": {"blocks": [], "mobs": []}},
           "task": task}
    env.update(extra)
    return json.dumps(env)


@unittest.skipUnless(shutil.which("node"), "node is required to run scout.js")
class ScoutScriptTest(unittest.TestCase):

    def test_returns_exactly_the_parity_directive(self):
        # 8.2's subject, pinned in full. STORE_ALL is emitted BARE here on
        # purpose, and §3 pins that coordless form: it is what every producer in
        # this repo emits (agent.py:1622's pattern has no capture groups). The
        # form is CONSTRUCTED from code, not observed from TEST logs -- those
        # logs carry no current STORE_ALL record -- and §3 says so. Constructing
        # the coordless form holds constant a call the planner really makes,
        # rather than comparing it against one it never makes.
        result = _run(_envelope(20.0))
        self.assertEqual(result["actions"], [{"kind": "STORE_ALL"}],
                         f"script returned {result['actions']!r}, logs={result['logs']!r}")

    def test_no_snapshot_proposes_nothing_and_says_so(self):
        result = _run("undefined")
        self.assertEqual(result["actions"], [])
        self.assertTrue(any("no snapshot" in line for line in result["logs"]),
                        f"silence was unexplained: {result['logs']!r}")

    def test_low_health_holds(self):
        result = _run(_envelope(3.0))
        self.assertEqual(result["actions"], [])
        self.assertTrue(any("too low" in line for line in result["logs"]), result["logs"])

    def test_busy_bot_does_not_stack_a_second_action(self):
        result = _run(_envelope(20.0, {"type": "MINE"}))
        self.assertEqual(result["actions"], [],
                         "script started an action under one already in flight")

    def test_guards_fire_on_the_envelope_the_cache_actually_produces(self):
        # THE FIX FOR THE THIRD FIXTURE-VS-PRODUCER GAP.
        #
        # Every test above feeds scout.js a FLAT object like
        # {"health": 20, "task": null}. That is the shape the script wants, not
        # the shape it gets: production passes the envelope from
        # SnapshotCache.get, which is {"tick","server_ms","state","events",
        # "task"} with health inside `state`. So `snapshot.health` was
        # undefined, `typeof health === "number"` short-circuited, and the
        # low-health guard NEVER FIRED - a hurt bot still proposed STORE_ALL.
        # Three green suites could not see it because every fixture agreed with
        # the reader instead of with the producer.
        #
        # This builds the envelope THROUGH SnapshotCache and feeds the script
        # exactly that, so the guard is tested against bytes production emits.
        import snapshot as snap

        class _Api:
            def __init__(self, health, directive):
                self._health, self._directive = health, directive
            def status(self, bot):
                return {"health": self._health, "food": 18,
                        "position": {"x": 0.0, "y": 64.0, "z": 0.0,
                                     "dim": "minecraft:overworld"}}
            def inventory(self, bot): return []
            def blocks(self, bot, radius=8): return []
            def entities(self, bot, radius=24.0): return []
            def get_directive(self, bot): return self._directive

        def envelope_json(health, directive):
            cache = snap.SnapshotCache(_Api(health, directive), ttl=60.0,
                                       clock=lambda: 1000.0)
            return json.dumps(cache.get("Scout")[0])

        # Healthy and idle: acts, as before.
        healthy = _run(envelope_json(20.0, None))
        self.assertEqual(healthy["actions"], [{"kind": "STORE_ALL"}],
                         f"real envelope broke the happy path: {healthy}")

        # HURT and idle: must hold. This is the branch that never ran.
        hurt = _run(envelope_json(3.0, None))
        self.assertEqual(
            hurt["actions"], [],
            "a bot at health 3 still proposed an action - the low-health guard "
            "is not reading the envelope production sends")
        self.assertTrue(any("too low" in line for line in hurt["logs"]),
                        f"held without saying why: {hurt['logs']!r}")

        # Task in flight: holds, and now on the real envelope rather than a
        # flat one - the task-guard fix at snapshot.py:144.
        busy = _run(envelope_json(20.0, {"type": "MINE", "status": "running"}))
        self.assertEqual(busy["actions"], [],
                         "script started an action under one already in flight")

    def test_zero_actions_paths_are_distinguishable_from_a_silent_script(self):
        # A script that returns [] because it CHOSE to is different from one
        # that failed. The three empty-return paths above each log a reason or
        # are a deliberate no-op (busy); the busy path logs nothing because the
        # agent already knows why. This asserts the two self-explaining paths
        # do explain, so 8.2 can tell "held" from "broke".
        for literal, token in (("undefined", "no snapshot"),
                               (_envelope(3.0), "too low")):
            logs = _run(literal)["logs"]
            self.assertTrue(any(token in line for line in logs),
                            f"{literal} returned [] without explaining: {logs!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)

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


@unittest.skipUnless(shutil.which("node"), "node is required to run scout.js")
class ScoutScriptTest(unittest.TestCase):

    def test_returns_exactly_the_parity_directive(self):
        # 8.2's subject, pinned in full. STORE_ALL is emitted BARE here on
        # purpose: this is the form the planner's seed match produces
        # (agent.py:1888, whose pattern has no capture groups). The parity test
        # therefore holds the argument form CONSTANT between paths -- it is not
        # constructing a coords-bearing call the planner never makes. That
        # distinction is the difference between the test proving agreement and
        # the test proving only that the harness agrees with itself.
        result = _run('{"health": 20, "task": null}')
        self.assertEqual(result["actions"], [{"kind": "STORE_ALL"}],
                         f"script returned {result['actions']!r}, logs={result['logs']!r}")

    def test_no_snapshot_proposes_nothing_and_says_so(self):
        result = _run("undefined")
        self.assertEqual(result["actions"], [])
        self.assertTrue(any("no snapshot" in line for line in result["logs"]),
                        f"silence was unexplained: {result['logs']!r}")

    def test_low_health_holds(self):
        result = _run('{"health": 3, "task": null}')
        self.assertEqual(result["actions"], [])
        self.assertTrue(any("too low" in line for line in result["logs"]), result["logs"])

    def test_busy_bot_does_not_stack_a_second_action(self):
        result = _run('{"health": 20, "task": "MINE"}')
        self.assertEqual(result["actions"], [],
                         "script started an action under one already in flight")

    def test_zero_actions_paths_are_distinguishable_from_a_silent_script(self):
        # A script that returns [] because it CHOSE to is different from one
        # that failed. The three empty-return paths above each log a reason or
        # are a deliberate no-op (busy); the busy path logs nothing because the
        # agent already knows why. This asserts the two self-explaining paths
        # do explain, so 8.2 can tell "held" from "broke".
        for literal, token in (("undefined", "no snapshot"),
                               ('{"health": 3, "task": null}', "too low")):
            logs = _run(literal)["logs"]
            self.assertTrue(any(token in line for line in logs),
                            f"{literal} returned [] without explaining: {logs!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)

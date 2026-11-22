#!/usr/bin/env python3
"""Tests for agent/scripts/mystic.js — the prod step-4 script.

WHAT THIS IS FOR: step 4 turns script mode on for ONE prod bot. The wiring is
the point, but the script still has to be driven through the real runner to know
it emits exactly one MINE and nothing else -- a script that returns an array
instead of calling api.do looks fine in review and ships zero actions
(scout.js:218-232 records that exact measured bug).

The driver, the runner-root lookup and the envelope builder are NOT reimplemented
here: they are imported from test_scout_script, because a second copy of the
driver is a second thing to drift, and the fixtures there are copied from the
producer's real responses rather than written to suit the script.

THE RECORD SHAPE, measured not assumed (this file's first draft got it wrong):
the runner's action record is {"seq", "call", "directive", "args"} where
`directive` is the KIND STRING ("MINE") and the arguments are in `args`. It is
not {"kind": ...} with the fields inline. `memory` passed to _run() is a DICT,
not JSON text -- the driver base64-encodes it for decodeMemory, and handing it a
JSON string makes recall() return null, which silently disables any cooldown
test that relies on it.

Two deliberate fixture shapes:
  - idle uses IDLE_DIRECTIVE, the real "Standing by" object with
    progress.phase "idle" -- not `task: None`, which production never sends and
    which once hid three dead guards in scout.js's suite.
  - busy uses BUSY_DIRECTIVE, a genuinely in-flight directive.
"""
import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
# Import the sibling harness by path, so this suite runs from any cwd (the
# repo root, agent/, or a reviewer's tree) rather than only from agent/.
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import test_scout_script as _ts

_MYSTIC = os.path.join(_HERE, "scripts", "mystic.js")

# Past this many ticks after the last dispatch, mystic.js mines again.
MINE_COOLDOWN_TICKS = 200


def _run(snapshot, memory=None):
    """Drive mystic.js through the real runner. Raises if the runner is absent
    rather than passing against a stand-in."""
    return _ts._run(snapshot, script_path=_MYSTIC, memory=memory)


def _actions(out):
    return out.get("actions") or []


def _kinds(out):
    """The directive kind of each collected action, in call order."""
    return [a["directive"] for a in _actions(out)]


@unittest.skipUnless(_ts.shutil.which("node"), "node is required to run mystic.js")
class MysticScriptTest(unittest.TestCase):

    def test_idle_bot_dispatches_exactly_one_mine(self):
        """The core assertion: one action, and it is MINE.

        Pinned as the full record, the way scout.js's parity test pins its own:
        a partial assertion would pass if the script emitted MINE twice, or
        emitted it with the wrong arguments.
        """
        out = _run(_ts._envelope(task=_ts.IDLE_DIRECTIVE))
        self.assertTrue(out["ok"], f"engine rejected the script: {out['error']}")
        self.assertEqual(
            out["actions"],
            [{"seq": 1, "call": "do", "directive": "MINE",
              "args": {"target": "minecraft:dirt", "count": 3, "radius": 128}}],
            f"script emitted {out['actions']!r}, logs={out['logs']!r}")

    def test_action_arrives_through_api_do_not_a_returned_array(self):
        """The run-3 regression class, pinned directly: the runner ignores a
        script's return value and collects only api.do calls (contract §4.4)."""
        out = _run(_ts._envelope(task=_ts.IDLE_DIRECTIVE))
        self.assertEqual(len(_actions(out)), 1)
        self.assertEqual(_actions(out)[0]["call"], "do",
                         "the action must arrive through api.do; the runner "
                         "ignores a script's return value (§4.4)")
        self.assertGreaterEqual(out["host_calls"], 1,
                                "an api.do call must register as a host call")

    def test_mine_carries_a_non_blank_target(self):
        """MINE without `target` binds and then kills the tick loop
        (action_binding.py:70; planner.py:196-200). A blank target reaches the
        same NPE as a missing one (action_binding.py:132), so this asserts the
        value is real, not merely present."""
        args = _actions(_run(_ts._envelope(task=_ts.IDLE_DIRECTIVE)))[0]["args"]
        target = args.get("target")
        self.assertTrue(str(target or "").strip(),
                        f"target must be a real block id, got {target!r}")

    def test_busy_bot_does_not_stack_a_second_action(self):
        """BUSY_DIRECTIVE is genuinely in flight; a second MINE underneath it is
        the stacking bug scout.js:161-215 describes."""
        out = _run(_ts._envelope(task=_ts.BUSY_DIRECTIVE))
        self.assertEqual(_actions(out), [],
                         f"busy bot must propose nothing, got {out['actions']!r}")

    def test_terminal_directives_do_not_silence_the_script(self):
        """A finished bot reports a terminal status beside state "Standing by"
        forever. That is idle and must mine -- the M3-1b case."""
        for task in (_ts.COMPLETED_SKILL_DIRECTIVE, _ts.COMPLETED_DONE_DIRECTIVE):
            with self.subTest(status=task["directive"]["status"]):
                out = _run(_ts._envelope(task=task))
                self.assertEqual(_kinds(out), ["MINE"],
                                 f"{task['directive']['status']} bot should mine, "
                                 f"got {out['actions']!r}")

    def test_low_health_holds(self):
        out = _run(_ts._envelope(health=3.0, task=_ts.IDLE_DIRECTIVE))
        self.assertEqual(_actions(out), [], f"hurt bot must not mine, got {out['actions']!r}")

    def test_no_snapshot_proposes_nothing(self):
        out = _run(None)
        self.assertEqual(_actions(out), [],
                         f"no snapshot must propose nothing, got {out['actions']!r}")

    def test_cooldown_suppresses_a_second_dispatch(self):
        """Within the cooldown the script must hold. If the memory key or the
        parse were wrong the guard would never fire and this would see a second
        action -- the silent-dead-guard class scout.js's inventory path shows."""
        out = _run(_ts._envelope(tick=101, task=_ts.IDLE_DIRECTIVE),
                   memory={"lastMineTick": 100})
        self.assertEqual(_actions(out), [],
                         f"within cooldown must propose nothing, got {out['actions']!r}")
        self.assertTrue(any("cooling down" in line.lower() for line in out["logs"]),
                        f"held without saying why: {out['logs']!r}")

    def test_cooldown_expires(self):
        """The complement: past the cooldown it must act again, or the guard
        would hold a bot forever."""
        out = _run(_ts._envelope(tick=100 + MINE_COOLDOWN_TICKS + 1,
                                 task=_ts.IDLE_DIRECTIVE),
                   memory={"lastMineTick": 100})
        self.assertEqual(_kinds(out), ["MINE"],
                         "cooldown never expired; the bot would mine once and stop")

    def test_script_remembers_the_tick_it_fired(self):
        """The stamp must reach remember(), or the cooldown has nothing to read
        next tick. memoryOut is the runner's JSON string, not a live object."""
        out = _run(_ts._envelope(tick=55, task=_ts.IDLE_DIRECTIVE))
        self.assertEqual(_kinds(out), ["MINE"])
        blob = out.get("memory")
        self.assertIsNotNone(blob, "dispatched without remembering the tick")
        self.assertEqual(json.loads(blob).get("lastMineTick"), 55)

    def test_remembered_keys_are_preserved(self):
        """The memory blob is shared with the planner's own usage, so mystic.js
        must preserve keys it does not own rather than overwrite the blob."""
        out = _run(_ts._envelope(tick=60, task=_ts.IDLE_DIRECTIVE),
                   memory={"someoneElse": "keep-me"})
        self.assertEqual(_kinds(out), ["MINE"])
        blob = json.loads(out["memory"])
        self.assertEqual(blob.get("someoneElse"), "keep-me",
                         f"dropped a key it does not own: {blob!r}")
        self.assertEqual(blob.get("lastMineTick"), 60)


if __name__ == "__main__":
    unittest.main()

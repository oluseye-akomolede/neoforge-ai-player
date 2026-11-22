"""The runner's fixture must be what this repo's producer emits, and nothing else.

`agent-script-runner/test/fixtures/envelope-from-producer.json` is named after
its provenance, and the lookup tests read it as if it were the wire. Twice that
name was a lie: once when the world sat at the top level instead of under
`nearby`, and once when every position was a hand-written string ("16.5, 86.0,
-15.5") while the mod sends an {x,y,z} map. Both times the fixture, the
generator and the tests agreed with each other about a shape the game has never
sent, so every test passed while the live bot saw something else.

These tests pin the two things that let that happen:
  * regenerating the generator reproduces the committed bytes (so a hand-edit
    or a partial regeneration is caught), and
  * the positions in it have the type the Java actually sends -- maps for
    positions, a string only where the Java formats one.

They do not run the game. The producer's shape is taken from the Java this
repo compiles, cited per field, which is the closest this harness can get.
"""

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))

import gen_envelope_fixture as gen  # noqa: E402

FIXTURE = os.path.join(
    HERE, "..", "..", "agent-script-runner", "test", "fixtures",
    "envelope-from-producer.json")


def _generate():
    """Run the generator's main() into a string, exactly as the shell does."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        gen.main()
    return buf.getvalue()


class FixtureMatchesItsGeneratorTest(unittest.TestCase):
    def test_the_committed_fixture_is_what_the_generator_emits(self):
        # If this fails, someone hand-edited the fixture or changed the
        # generator without regenerating. Regenerate with:
        #   python3 agent/tools/gen_envelope_fixture.py > \
        #     ../agent-script-runner/test/fixtures/envelope-from-producer.json
        if not os.path.exists(FIXTURE):
            self.skipTest("agent-script-runner worktree not checked out beside this one")
        with open(FIXTURE) as fh:
            committed = fh.read()
        self.assertEqual(
            committed, _generate(),
            "the runner's fixture is not what this repo's generator emits")

    def test_regeneration_is_deterministic(self):
        # The comparison above is only meaningful if the output is stable; an
        # unpinned clock or a set-ordered list would make it fail at random
        # and teach everyone to ignore it.
        self.assertEqual(_generate(), _generate())


class PositionShapeTest(unittest.TestCase):
    """Positions are {x,y,z} maps, because the Java builds Maps for them."""

    def setUp(self):
        self.env = json.loads(_generate())

    def test_the_bots_own_position_is_a_map(self):
        # BotPlayer.formatPos returns Map<String,Double> {x,y,z}, rounded to
        # 1dp (BotPlayer.java:1235-1240), and getStatus puts it at "position".
        pos = self.env["state"]["position"]
        self.assertIsInstance(pos, dict, f"position is {type(pos).__name__}, not a map")
        self.assertEqual(set(pos), {"x", "y", "z"})

    def test_block_positions_are_maps_of_ints(self):
        # NearbyBlockIndex.positionOf returns Map<String,Integer> {x,y,z}
        # (:113-120). Ints, not doubles: a block sits on a whole coordinate.
        blocks = self.env["state"]["nearby"]["blocks"]
        self.assertTrue(blocks)
        for b in blocks:
            pos = b["position"]
            self.assertIsInstance(pos, dict, f"block position is {pos!r}")
            self.assertEqual(set(pos), {"x", "y", "z"})
            for axis in ("x", "y", "z"):
                self.assertIsInstance(pos[axis], int, f"{axis} is not an int: {pos!r}")

    def test_entity_positions_are_maps(self):
        # collectEntities puts formatPos(entity.position()) at "position"
        # (BotPlayer.java:884).
        mobs = self.env["state"]["nearby"]["mobs"]
        self.assertTrue(mobs)
        for m in mobs:
            self.assertIsInstance(m["position"], dict, f"mob position is {m['position']!r}")

    def test_distance_stays_a_string_because_the_java_formats_it(self):
        # BotPlayer.java:886 -- String.format("%.1f", entity.distanceTo(player)).
        # Widening this to a number would be as wrong as the positions were.
        for m in self.env["state"]["nearby"]["mobs"]:
            self.assertIsInstance(m["distance"], str, f"distance is {m['distance']!r}")


if __name__ == "__main__":
    unittest.main()

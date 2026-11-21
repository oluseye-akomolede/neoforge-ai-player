#!/usr/bin/env python3
"""Emit the tick envelope the game actually sends, as a test fixture.

Why this exists: `agent-script-runner`'s lookup tests used a hand-written
`world()` fixture shaped `{capturedAt, self, nearby}`. The agent never sends
that shape -- `snapshot.build_envelope` returns
`{tick, server_ms, state, events, task}` and the world lives at `state.nearby`.
`look` read `snapshot.nearby`, so against the hand-written fixture it found the
world and against the real envelope it found nothing, and every test passed.
Two bots idled with the trigger in plain sight (2026-11-21).

The fix is not "correct the fixture once": it is to DERIVE the fixture from the
producer, so a future change to the envelope's shape moves the fixture with it
and the lookup test fails at the same moment the wire changes.

Usage:
    python3 agent/tools/gen_envelope_fixture.py \\
        > ../agent-script-runner/test/fixtures/envelope-from-producer.json

`server_ms` is pinned to a constant rather than `time.time()` so the output is
byte-stable: a regenerated fixture that differs only by a clock reading would
show up as a diff on every run and hide a real shape change in that noise.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import snapshot  # noqa: E402

# A world that carries both things the trial's scripts were looking for, at the
# positions the lead placed them: iron_ore inside the 5-block block radius, a
# sheep inside the 16-block entity radius.
STATE = {
    "position": "16.5, 86.0, -15.5",
    "inventory": [],
    "health": 20.0,
    "nearby": {
        "blocks": [
            {"id": "minecraft:iron_ore", "block": "iron_ore",
             "position": "18 86 -15"},
            # Two chests so the immutability and re-query tests have a stable
            # pair to compare; the trial's iron_ore and sheep stay so the
            # fixture still describes the world the two bots idled in.
            {"id": "minecraft:chest", "block": "chest",
             "position": "17 86 -15"},
            {"id": "minecraft:chest", "block": "chest",
             "position": "17 86 -14"},
        ],
        "mobs": [
            {"type": "minecraft:sheep", "name": "Sheep",
             "position": "19.5 86 -13.5", "distance": "3.6"},
        ],
    },
    "task": None,
}

COMMENT = (
    "GENERATED, do not hand-edit. Produced by agent/snapshot.py::build_envelope "
    "in the neoforge-ai-player repo. Regenerate with: "
    "python3 agent/tools/gen_envelope_fixture.py > "
    "../agent-script-runner/test/fixtures/envelope-from-producer.json . "
    "The point of this file is that the lookup tests read the SAME shape the "
    "game sends: the world is at state.nearby, not at nearby. A hand-written "
    "fixture that puts nearby at the top level is exactly the shape that hid "
    "the 2026-11-21 wrong-depth bug."
)


def main():
    envelope = snapshot.build_envelope(STATE, tick=1, events=[], task=None)
    # The pin below overwrites a field the producer must still be emitting.
    # `server_ms` is the one field look.age() reads, so if build_envelope ever
    # renamed it, the overwrite would silently create the key, and generator,
    # fixture and age test would all keep agreeing with each other about a
    # field production no longer sends. Fail here instead.
    if "server_ms" not in envelope:
        raise SystemExit(
            "build_envelope no longer emits 'server_ms'; look.age() reads it. "
            "Update snapshot.build_envelope, look.js and this pin together."
        )
    # Pin the clock so the file is stable. build_envelope reads time.time().
    envelope["server_ms"] = 1795292996127
    out = {"_comment": COMMENT}
    out.update(envelope)
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

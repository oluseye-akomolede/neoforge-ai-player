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

# The GAME's answers, not the snapshot's. This dict used to be the state that
# build_state was supposed to produce, with nearby.blocks written as a plain
# list -- so the generator, the fixture and the lookup tests all agreed on a
# shape the game has never sent, while state.nearby.blocks() on a live bot held
# {"blocks": [...]} and every script saw an empty world. The fixture is only
# worth having if it comes out of the code that makes the envelope, so this is
# hand-written as the WRAPPED responses of HttpApiServer.java:469/504/505 and
# goes through build_state below.
RAW_RESPONSES = {
    "position": "16.5, 86.0, -15.5",
    # Non-empty so the look.inventory() tests prove something: an empty
    # inventory would make every inventory assertion pass vacuously, which is
    # the same defect as a fixture that mirrors the bug it should catch. These
    # are the shears the 2026-11-21 sheep script lacked, so a test can ask "is
    # the tool for this task in hand" against data shaped like a real answer.
    # Field names are BotPlayer.serializeItemStack's (BotPlayer.java:997-1003),
    # the path the snapshot reads: {slot, item, count, display_name,
    # max_stack_size}. NOT the {slot, nbt} shape on the other HTTP route.
    # HttpApiServer:469 -- one-key wrapper, exactly like the other two.
    "inventory": {"inventory": [
        {"slot": 0, "item": "minecraft:shears", "count": 1,
         "display_name": "Shears", "max_stack_size": 1, "durability": 238,
         "max_durability": 238},
        {"slot": 1, "item": "minecraft:iron_ore", "count": 12,
         "display_name": "Iron Ore", "max_stack_size": 64},
    ]},
    "health": 20.0,
    # HttpApiServer:505 -- blocks arrives wrapped in "blocks".
    "blocks": {"blocks": [
        {"id": "minecraft:iron_ore", "block": "iron_ore",
         "position": "18 86 -15"},
        # Two chests so the immutability and re-query tests have a stable
        # pair to compare; the trial's iron_ore and sheep stay so the
        # fixture still describes the world the two bots idled in.
        {"id": "minecraft:chest", "block": "chest",
         "position": "17 86 -15"},
        {"id": "minecraft:chest", "block": "chest",
         "position": "17 86 -14"},
    ]},
    # HttpApiServer:504 -- entities arrives wrapped in "entities"; the
    # snapshot's key for it is "mobs".
    "entities": {"entities": [
        {"type": "minecraft:sheep", "name": "Sheep",
         "position": "19.5 86 -13.5", "distance": "3.6"},
    ]},
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


class _FixtureApi:
    """Answers as the mod does: wrapped observations, plain status/directive."""

    def status(self, bot):
        return {"health": RAW_RESPONSES["health"],
                "position": RAW_RESPONSES["position"]}

    def get_directive(self, bot):
        return None

    def inventory(self, bot):
        return RAW_RESPONSES["inventory"]

    def blocks(self, bot, radius=8):
        return RAW_RESPONSES["blocks"]

    def entities(self, bot, radius=24.0):
        return RAW_RESPONSES["entities"]


def main():
    # Through build_state, so the fixture is what the producer actually emits.
    # Skipping this is how the file came to describe a world no live bot sends.
    state, errors = snapshot.build_state(_FixtureApi(), "fixture")
    if errors:
        raise SystemExit(f"build_state reported reader errors: {errors}")
    for key in ("inventory", "blocks", "mobs"):
        value = state[key] if key == "inventory" else state["nearby"][key]
        if not isinstance(value, list):
            raise SystemExit(
                f"state {key} is {type(value).__name__}, not list -- the "
                "wrapper reached the fixture. Fix snapshot.build_state, not this."
            )
    envelope = snapshot.build_envelope(state, tick=1, events=[], task=None)
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

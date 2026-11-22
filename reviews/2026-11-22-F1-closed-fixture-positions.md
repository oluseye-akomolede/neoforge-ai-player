# Review: F-1 closed — the producer fixture now sends the shape the game sends

Revs: agent `039143d` (parent `e17bee4`), runner `8834ac0` (parent `beb8ee7`).
Both on `ship-ca27-harness`; neither is an ancestor of `minecraft-wt-qwen`,
so both were checked out explicitly for every run below.

Verdict: **PASS. F-1 closed.** One stale comment to fix (N-1), no behaviour on it.

## The fix is the one asked for

`gen_envelope_fixture.py:53-87` now emits `{x,y,z}` maps for the bot position,
every block position and the entity position, and leaves `distance` a string.
That is exactly the scoped change; nothing else moved.

Verified against the Java at `039143d`, not against the commit message:

| field | Java | fixture now | |
|---|---|---|---|
| `state.position` | `formatPos` -> `Map<String,Double>` (`BotPlayer.java:762,820`) | `{"x":16.5,"y":86.0,"z":-15.5}` | correct |
| block `position` | `positionOf` -> `Map<String,Integer>` (`NearbyBlockIndex.java:114`) | `{"x":18,"y":86,"z":-15}` | correct |
| entity `position` | `formatPos` | `{"x":19.5,"y":86.0,"z":-13.5}` | correct |
| entity `distance` | `String.format("%.1f",...)` (`BotPlayer.java:886`) | `"3.6"` | correct, **unchanged** |

`distance` staying a string is the part of my finding that was easy to get
wrong, and they did not "fix" it. Good.

## Driving the fixture through the real lookups

The point of the fixture is that tests read it, so I read it the same way a
script does (`createLook` over the committed file at `8834ac0`):

    look.blocks("minecraft:iron_ore") -> matches[0].position = {x:18,y:86,z:-15}
                                         b.position.x === 18  (typeof object)
    look.entities("minecraft:sheep")  -> {..., position:{x:19.5,y:86,z:-13.5},
                                          distance:"3.6"}
                                         typeof distance = string
    look.self()                       -> {ok:true, position:{x:16.5,y:86,z:-15.5},
                                          health:20, food:null}

The silent `position:null` I filed against `look.self(fixture)` is gone.

My first attempt to read `nearby` returned null. That was my error: `nearby`
nests under `state`, and I looked at the envelope top level -- the precise
wrong-depth mistake this fixture and its comment exist to prevent. The
generator raises rather than emitting a fixture without the lists, so its exit
0 is the evidence `nearby` is populated; I should have read the generator
before the shape.

## The fixture is genuinely generated

`python3 -B agent/tools/gen_envelope_fixture.py` at `039143d` diffs against
the committed `test/fixtures/envelope-from-producer.json` with **no structural
difference**. So the file is not a relabelled hand edit; it is what the
generator emits, and the generator now emits the game's shape. The spec
scenario "the fixture is the producer's own output" is now true in letter and
in spirit.

## Suites

- runner, declared script (`node --test --test-timeout=40000 "test/*.test.mjs"`):
  **195 pass, 0 fail**, rc=0.
- agent, `test_agent_script_branch test_action_binding test_script_prompt_kinds`
  from inside `agent/`: **161 tests, OK**, rc=0.
- `openspec validate script-lookups-and-results --strict`: valid, rc=0.

Both `look.test.mjs:34` and `look-engine.test.mjs:26` read the fixture, so the
fix makes real tests assert against the live shape rather than a parallel one.

## N-1 (minor): a comment that is now false

`test/look-engine.test.mjs:217-222` still says the fixture "carries position as
a comma-joined string" and uses that to justify building `bodySnapshot`
instead. At `8834ac0` that sentence is false. The helper is still reasonable,
but its stated reason no longer exists, and a reader who trusts it will
re-derive the wrong conclusion about the fixture. Reword to keep the real
reason (the helper varies one field at a time) and drop the claim. This is the
only place in either repo with that wording; I checked both.

Not a blocker: it is a comment, the tests it sits above are correct, and it is
one commit behind a change that invalidated it.

## Not established

Nothing ran against a live bot. The shapes above are read from the Java and
driven through the real envelope builder and the real lookups, not observed in
a session. The trial-4.3 end-to-end run remains the confirmation nobody on
these seats can make.

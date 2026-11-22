# Review: trial 4.3 — `look.self()` and the script spin guard

Revs: runner `beb8ee7` (agent-script-runner), agent `e17bee4` (parent
`3af7309`, on `ship-ca27-harness`). Neither agent rev is an ancestor of
`minecraft-wt-qwen`; both checked out explicitly for every run.

Verdict: **PASS on the two commits, HOLD on the producer fixture** (F-1).

## The feature works, end to end

`look.self()` normalises `state.position` only when it is an object
(`look.js:151-152`) and reports a missing body as `no-self`, not as a zero
position — the distinction that matters, since a zero position is a real place.

Driven with real envelopes through the real `createLook`:

| snapshot | `self()` |
|---|---|
| production shape (`snapshot.build_state` over a `getStatus`-shaped map) | `{ok:true, position:{x:16.5,y:86,z:-15.5}, health:20, food:20}` |
| committed fixture | `{ok:true, position:null, health:20, food:null}` |
| no position | `{ok:true, position:null, ...}` |

The first row is the production path and it is correct.

## The spin guard

`_script_action_key` is order-independent and distinguishes a changed
coordinate and a changed kind; `_note_script_repeat` resets on
`len(ran_keys)!=1` and on a changed key. Driven from a fresh state:

    repeat same 5x     -> [F,F,F,F,T]
    after yield reset, alternating -> [F,F,F,F]
    all-refused []     -> [F,F,F]

Mutants (each restored byte-identically with `cmp`):
- key reduced to kind -> 1 FAIL, `test_a_different_coordinate_is_a_different_action`
- spin yield disarmed -> 3 FAIL by name

Their account of the earlier surviving mutant is accurate: reducing the key to
kind was unobservable until the two reset tests existed.

## Suites

- runner `npm test` (the declared script): **195 pass, 0 fail**, rc=0.
- agent `test_agent_script_branch test_action_binding test_script_prompt_kinds`: **161 OK**, rc=0.
- `openspec validate script-lookups-and-results --strict`: valid, rc=0.

## F-1: the producer fixture is generated, and still wrong

The builder's separate finding is half right and the half that is wrong
matters for the fix.

`test/fixtures/envelope-from-producer.json` IS the output of
`gen_envelope_fixture.py` (a structural diff shows only `health` field order)
— and the generator's fake API hard-codes
`"position": "16.5, 86.0, -15.5"` at `gen_envelope_fixture.py:42`.

The Java sends a **map**: `BotPlayer.formatPos` returns
`Map<String, Double>` → `{x,y,z}` (`BotPlayer.java:1235-1240`), and
`NearbyBlockIndex.positionOf` returns `{x,y,z}` integers (`:113-120`). So:

| field | Java | generator/fixture | verdict |
|---|---|---|---|
| `state.position` | `{x,y,z}` numbers | `"16.5, 86.0, -15.5"` | **wrong** |
| block `position` | `{x,y,z}` ints | `"18 86 -15"` | **wrong** |
| entity `position` | `{x,y,z}` numbers | `"19.5 86 -13.5"` | **wrong** |
| entity `distance` | `String.format("%.1f")` | `"3.6"` | **correct** |

The builder listed `distance` as a defect; the Java at `BotPlayer.java:886`
formats it as a string, so the fixture matches and that part should not be
changed. The other three should.

**Why this is a hold and not a note:** the spec scenario at
`specs/bot-coded-agents/spec.md:480` ("The fixture is the producer's own
output") is satisfied in letter — the file does come from `build_envelope` —
and defeated in spirit, because the API the generator feeds `build_state` is a
shape the game never sends. `snapshot.build_state` passes
`status.get("position")` through untouched (`snapshot.py:115`), so the fixture
is a faithful record of a wrong input.

The generator was carefully corrected for the inventory and block *wrappers*,
with comments citing the exact Java lines; the position fields kept their old
string form and carry no such comment. `gen_envelope_fixture.py:112-114` even
warns "Skipping this is how the file came to describe a world no live bot
sends" — the warning is about the wrapper and the same fault survives in the
values.

**Recommended fix:** make `RAW_RESPONSES["position"]` a `{x,y,z}` map, and the
block/entity positions too, then regenerate. Leave `distance` a string. That
single change turns the fixture into what its name claims and makes the
existing lookup tests assert against the live shape.

## Not established

Nothing ran against a live bot. `look.self()`'s shape is read from the Java
and driven through the real envelope builder, not observed in a session. The
trial-4.3 end-to-end run — a script GOTO that arrives and stops re-issuing —
is the confirmation this review cannot make.

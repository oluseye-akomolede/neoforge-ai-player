# Review: namespace-agnostic look matching + `look.inventory()` (2 repos)

Row `qitem-20261121205047-46d3851df2b27d94`. Reviewer: minecraft-reviewer@minecraft.
Date: 2026-11-21.

| Repo | Rev | Branch |
|---|---|---|
| agent-script-runner | `c6c3233` | `minecraft-wt-deepseek` |
| neoforge-ai-player | `9f9ed94` | `minecraft-wt-deepseek` |

**Verdict: PASS with one finding (N-1).** Both parts are correct, both are
tested, and every mutant I ran reds. N-1 is a spec/test scope mismatch that
does not block the code.

All commands run from `/home/sigmastrain/minecraft-wt-deepseek/`. Every mutant
was restored and verified with `cmp` before the next step; both trees are clean
at the revs above.

---

## What I ran, and the numbers I got

| Check | Result |
|---|---|
| runner, declared suite (`npm test`) on `c6c3233` | **189/189**, rc=0 |
| agent, `test_l3_script_path` on `9f9ed94` | **Ran 90, OK** |
| fixture regenerated from `gen_envelope_fixture.py` vs committed | **byte-identical, 1653 bytes** |
| `openspec validate script-lookups-and-results --strict` | **valid, rc=0** |
| rendered L3 prompt brace artefacts | **0 `{{`, 0 `}}`** |

The fixture regeneration is the claim I most wanted to check myself, because
`state.inventory` is now non-empty and the generator is the only thing standing
between the tests and a hand-written shape. It is the producer's own output.

I confirmed the two `BotPlayer.java` cites rather than taking them:

- `BotPlayer.java:910` — `BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString()`,
  so the block id the game sends **is** namespaced. The premise of Part 1 is real.
- `BotPlayer.java:997-1003` — `serializeItemStack` really does emit
  `{slot, item, count, display_name, max_stack_size, [durability, max_durability]}`,
  matching the fixture field-for-field. The builder's note that it nearly used the
  other route's `{slot, nbt}` shape is the right call and the fixture shows it.

---

## Part 1 — namespace-agnostic matching

`__lookBare` strips **one** leading `minecraft:` from each side and rewrites
nothing else. Correct at every direction I probed directly against `createLook`
(not through their tests):

| needle / entry id | matches |
|---|---|
| `minecraft:iron_ore` / `iron_ore` | 1 |
| `iron_ore` / `iron_ore` | 1 |
| `minecraft:iron_ore` / `minecraft:iron_ore` | 1 |
| `iron_ore` / `minecraft:iron_ore` | 1 |
| `minecraft:b` / `a:minecraft:b` | **0** (one prefix only) |
| `Minecraft:Iron_Ore` / `minecraft:iron_ore` | 1 (case-insensitive) |

The id-vs-display-name tests give the entry a display name that matches nothing
under test (`"Some Display Name"`), which is what makes the id branch the only
thing that can pass them. Without that, strip-the-id and strip-the-needle are
indistinguishable — the builder found that gap themselves and closed it.

## Part 2 — `look.inventory()`

Reads `state.inventory` from the snapshot in hand, returns a deep copy, `items: []`
on an empty or absent inventory rather than throwing, and adds no host call
(the answers are not promises). Frozen object, frozen `radius`.

---

## Mutants (each restored and `cmp`-checked)

Runner, full declared suite, baseline 189/189:

| Mutant | fails |
|---|---|
| strip neither side (`wanted.toLowerCase()`) | **11** |
| strip only the needle, not the id | **1** |
| greedy `/.*minecraft:/` regex | **1** |
| shallow inventory copy | **1** |
| wrong read path (`__snapshot.nearby.inventory`) | **6** |
| non-frozen `look` | **1** |

Agent prompt, `test_l3_script_path`, baseline 90 OK:

| Mutant | result |
|---|---|
| remove the `look.inventory()` line | FAILED 1 |
| replace the tool-check instruction | FAILED 1 |
| remove the "missing tool" advice | FAILED 1 |
| remove the read-only claim | FAILED 1 |

The greedy-regex mutant failing only **1** is worth a note: `text.replace(/.*minecraft:/, "")`
is caught only by the `a:minecraft:b` scenario. That is a genuinely narrow
mutant and one test is the right size for it.

---

## N-1 — the spec scenario describes a check the test does not make

Scope mismatch, not a code defect. **Does not block.**

`openspec/.../spec.md:108-112`, scenario *"The inventory is readable with no
host call"*:

> **AND** `hostCalls` for the tick is unchanged by the call

No test measures `hostCalls`. The test that carries this scenario's name is
`look needs no host call to answer` (`look.test.mjs:245`), and it asserts
`typeof answer?.then === "undefined"` — "not a promise, so no round trip". That
is a reasonable proxy at the lookup layer, and it is a different claim from
counting host calls.

This matters more than usual here, because **the row exists because a script
idled on a missing tool**, and the entire value of `look.inventory()` is that it
lets the planner check *without spending the budget it is trying to protect*.
The inventory answer re-renders a snapshot the tick already holds, so I expect
the claim to be true — but "I expect it to be true" is not what a MUST in a
scenario is for.

Two honest fixes, either acceptable:

1. Move the `hostCalls` assertion to a binding-level test — call
   `look.inventory()` inside `Sandbox.evaluate` and assert the charged-host-call
   count is unchanged. This is the real claim.
2. Soften the scenario to what is tested: *"AND the answer is available without
   awaiting anything"*, and leave host-call accounting to the existing
   binding-level suite.

I did **not** run the binding-level probe: that is a separate instrument
(`binding.js` + `engine.js`) and this review is of `look.js`. So my statement is
scoped — the lookup is not a promise; whether the binding charges it is not
something I checked.

---

## Verified myself on this row (so not carried)

- runner **189/189** via the declared `npm test` script
- agent `test_l3_script_path` **Ran 90, OK**
- fixture regenerate **byte-identical**, 1653 bytes, inventory
  `[('minecraft:shears', 1), ('minecraft:iron_ore', 12)]`
- `openspec validate --strict` rc=0, "is valid"
- rendered prompt: 0 doubled braces, all four new prompt fragments present
- 10 mutants across both repos, each restored with `cmp`

## Not verified by me

- The full agent discovery figure (`Ran 478, errors=1`, uvicorn). Out of scope
  for this row and unchanged from the pre-existing dashboard import.
- The binding-level `hostCalls` claim in N-1 (see above).
- Anything live: no pod, no trial rerun. The row says so and I agree.

## One instrument note, against myself

My first read of the rendered prompt imported `planner.PLANNER_PROMPT` directly
and reported `9` doubled braces and all four fragments **absent**. That was the
wrong artefact — `PLANNER_PROMPT` is the module-level template, and the live
path is `l3_planner.render_script_system_prompt`. Through the production
renderer: **0 braces, 4/4 fragments present**. I nearly filed the opposite of
the truth. Recording it because the builder has now twice flagged the same
class of error, and this time it was mine.

## Archive note (still standing, unchanged)

`script-say-dedupe` stays ADDED-only; `ai-written-scripts` or `coded-agents`
archives before it (`c4ee233` §6). Nothing in this row changes that.

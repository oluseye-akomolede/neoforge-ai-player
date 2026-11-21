# Review — `8200b09` planner prompt documents `look` and `api.result`

Rev: `8200b09` on `ship-ca27-harness` (on `38eb1c4`).
Requested by minecraft-builder@minecraft 2026-11-21 19:16Z.
Reviewer: minecraft-reviewer@minecraft.

## Verdict

**PASS with F-1.** The gap it closes is real and the prompt is accurate against
the runner at `bdaeeb7`. One test under-implements its own spec sentence; the
prompt text itself is correct.

## The budget classification is right

The load-bearing claim is which calls spend one of the 8 host calls. Checked
against `src/binding.js` at `bdaeeb7`, not the commit message:

`accept()` is called at `:342` (`do`), `:359` (`say`), `:372` (`send`), `:413`
(`result`), `:434` (`remember`), `:474` (`log`) — **six**. `recall()` (`:395`)
returns `state.memoryIn` with no `accept()`, and its own comment says "NOT an
action and NOT a host call". `look` is built from `GUEST_SOURCE` in `look.js`
with zero `accept()`/`hostCall` references; `engine.js:758-768` documents it as
"pure value, not host functions … a lookup cannot spend".

So: six charged, `recall` and `look` free. The prompt's "At most 8 host calls …
`api.do`…`api.result` each count; `api.recall()` and `look` are free" is correct,
and the old "8 api calls" was indeed wrong once two of the names are free.

## The prompt matches `look.js` shape for shape

Verified each claim against `bdaeeb7:src/look.js`:

- `{ok:true, kind, matches}` — `:72` (blocks), `:85` (entities).
- `{ok:false, reason, message}` — `:51`, `:68`, `:81`, and the not-searched answer.
- `options.radius` "only narrows" — the guard is `asked > __LOOK_BLOCKS` (`:70`,
  `:83`): a larger radius answers not-searched, never widens.
- `look.age()` → `{ok:true, ageMs}` — `:95`. (It can also answer
  `ageMs: null` when the game sent no capture time; the prompt doesn't mention
  that, but it doesn't contradict it either — not a finding.)
- radii 5 and 16 — `BotPlayer.java:619-620`, read: `getNearbyEntities(16.0)`,
  `getNearbyBlocks(5)`.

`look.nearest` does not exist anywhere in the runner (`git grep nearest bdaeeb7
-- src/` is empty), so the builder's scenario-1 correction to
`look.entities('sheep')` was fixing a call that was never bound. `api.result`
costs a call (it calls `accept()` at `:413`) and `look` does not, exactly as the
prompt now says.

## F-1 — the radius test does not pin the entity radius

`test_the_prompt_states_the_real_radii_and_the_not_searched_answer` asserts:

```python
self.assertIn("5 blocks", prompt)   # unique in the prompt - this half holds
self.assertIn("16", prompt)         # NOT tied to the radius sentence
self.assertIn("not-searched-that-far", prompt)
```

**Mutant: entities 16 → 15 in the prompt. Suite stays green — 9 tests OK.**

The prompt contains **six** unrelated `16`s — "Craft 16x minecraft…", "Y=16",
"at least 16 cookies", "Smelt 16x…", "≤16 KB" — so `assertIn("16", prompt)` is
satisfied by any of them. The spec scenario (`spec.md:229-236`) states the
requirement correctly as one claim, "the real radii, blocks 5 and entities 16";
the test splits it and only pins the first half.

This is the same species the builder caught and fixed on the budget line (word
present, wrong side of the divide) — it just wasn't carried to the radii. A
regression where the mod's entity radius changes and the prompt isn't updated
would not redden this test.

**Fix** — tie 16 to its sentence, e.g.
`self.assertIn("entities within 16", prompt)`, or assert the rendered radius
line. Note `"5 blocks"` is already unique, so the asymmetry is only on the 16.

## Mutants I ran (all against the worktree, restored after)

| mutant | result |
|---|---|
| `api.result` moved into the free list | **red**, the budget test (as designed) |
| `look` moved into the charged list | **red**, the budget test |
| radii 5→8, 16→24 | **red**, radii test |
| drop the not-searched sentence | **red**, radii test |
| entities 16 → 15 | **green** — F-1 |
| `.format` render path | verified `_rendered_prompt()` uses the same three kwargs as `planner.py:214` |

The budget test's divide-then-assert shape (split on `" each count"`, assert each
call on its own side) works: both directions of the classification mutant red it.

The capture test drives the real `decompose` with a patched `requests.post` and
asserts on the actual request body — good, though it asserts only
`look.blocks(` / `api.result(`, so it would also survive a misspelt second call.

## Suites

- `test_planner_script_output` + `test_l3_script_path` + `test_agent_script_branch`:
  **Ran 169 tests, OK**, rc=0 (matches the builder's figure).
- `openspec validate script-lookups-and-results --strict`: valid, rc=0.
- Tasks 2.7 and 3.10 are ticked. Task 3.3 text now says the cooldown is the
  binding limit, matching F-4.
- Builder worktree clean after mutant runs (`git status --short` empty).

No `ollama-l3` requests, no pod exec, nothing in `ci`.

---

## Follow-up — F-1 closed at `88bcb12`

F-1 is fixed. Both radii are now tied to their own sentence:

```python
self.assertIn("blocks within 5 blocks", prompt)   # :146
self.assertIn("entities within 16", prompt)       # :147
```

and `"entities within 16"` is unique in `planner.py` (the literal is at `:151`
and appears once), so it can no longer be satisfied by a stray sixteen.

Mutants re-run against `88bcb12`, `-B` with `PYTHONDONTWRITEBYTECODE=1`, one at a
time, restore verified byte-identical (`cmp` against a backup, and the file
compared equal after each restore):

| mutant | result |
|---|---|
| clean baseline | 9 OK, rc=0 |
| entities 16 → 15 | **red** — `test_the_prompt_states_the_real_radii_and_the_not_searched_answer` |
| blocks 5 → 8 | **red** — same test |
| misspelt `look.entities` | **red** — `test_the_prompt_documents_look_and_result` and `test_the_real_prompt_renders_and_reaches_the_model` |
| clean again | 9 OK, rc=0 |

The builder's claims hold in every particular, including the capture-test
extension: a misspelt look name now reds two tests, not one.

**Correction to my own method.** My first run of these mutants reported M1 and
M2 green. That was wrong, and the fault was mine: a stale
`__pycache__/planner.cpython-312.pyc` (timestamped 19:19, and Python's
second-granularity pyc check does not notice a rewrite inside the same second)
shadowed the mutated source, so the suite re-ran the *unmutated* module. I
caught it by rendering the prompt directly with `-B`: the mutant text
(`entities within 15`) was present in the output, which proved the edit reached
the string while the suite still called it green. Re-run with bytecode disabled,
all three mutants red. Anything further I run in this repo will pass `-B`.

This is the same failure the builder described hitting ("the restore outran the
read"), from the other side — a cache, not a restore, but the same lesson: a
mutant result is only a fact if the instrument is proven to see the mutant.

# Review: 4f8ceb9 — dispatch-must-start (F1 fix on bd9f604)

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-17
Rev under review: 4f8ceb97df5d064d92a9a5ff4b53b3b289efc5cc (branch ship-ca27-harness)
Supersedes: e1318a9 (NOT PASS on bd9f604)
Obligation: qitem-20261117110822-f2724600be15fffe

## Verdict

**PASS**, with two findings, neither blocking.

F1 is fixed correctly and completely. `_dispatch_started` now handles all five
not-started shapes with a marker table, each marker is load-bearing, the
case-sensitivity distinction the builder nearly got wrong is real and correct,
and the 11-13 fail-open is closed end to end.

The findings are about **the spec's own coverage**, not the code: two of the
requirement's named not-started shapes have no scenario, and one cited line
number is wrong in three places.

## What I verified (all on a clean `git archive 4f8ceb9`)

### The function, against real strings

Called `_dispatch_started` directly on 13 inputs, each classified against the
ADDED requirement's definition at spec.md:59-60. **13/13 correct:**

| input | expected | got |
|---|---|---|
| `""` | False | False |
| `None` | False | False |
| `FAILED directive_never_started` | False | False |
| `FAILED dispatch_error Connection refused` | False | False |
| `DISPATCH_ERROR: Connection refused` | False | False |
| `FAILED bad_directive {'room':'x'}` | False | False |
| `FAILED ASK_PLAYER no question given` | False | False |
| `COMPLETED ok` | True | True |
| `FAILED directive_timeout 5.0s` | True | True |
| `FAILED reset` | True | True |
| `FAILED interrupted_by_chat` | True | True |
| `FAILED superseded` | True | True |
| `COMPLETED` | True | True |

The last five are the ones that must stay "started" — a directive that reached
the mod and then timed out did start. The fix preserves that.

### The case-sensitivity claim

The builder flagged that `dispatch_error` (lc) and `DISPATCH_ERROR` (uc) are not
redundant, having nearly deleted one. **Confirmed, and the direction is the
surprising one:**

- `'dispatch_error' in 'DISPATCH_ERROR: x'` → **False**. Lowercase is not a
  substring of uppercase. The lowercase marker does NOT catch the uppercase
  emitter.
- Removing `"dispatch_error"` alone: `_dispatch_started('FAILED dispatch_error x')`
  → **True** (want False). The gate opens.

Both markers are load-bearing. Good catch by the builder; the per-marker
mutation is what caught it.

### Each marker is load-bearing

Removed each of the five markers individually from `_NEVER_STARTED`, with the
anchor asserted unique before each run:

| marker removed | checks failed |
|---|---|
| `directive_never_started` | 3 |
| `dispatch_error` | 2 |
| `bad_directive` | 1 |
| `no question given` | 1 |
| `DISPATCH_ERROR` | 1 |

Every marker reddens on removal. No marker is decorative.

### The gate fires on a raised dispatch

`plan_orchestrator.py:660-666`: the `except` sets `last_result = f"DISPATCH_ERROR: {e}"`,
then `dispatched += 1` runs **after** the except block. So a raised dispatch is
counted as dispatched and (correctly) not started, and the gate at `:684`
(`if dispatched and not started`) fires. This is what closes the fail-open: the
error propagates as `subtask.error`, criteria are skipped, and the attempt does
not pass.

### Tests, suites, spec

- `test_dispatch_must_start.py`: **31 PASS, 0 FAIL**, rc=0 (run from file, no pipe)
- `test_action_binding.py`: **15 tests OK**, rc=0
- `tests/test_planner_prompts.py`: **8 tests OK**, rc=0
- `openspec validate dispatch-must-start --strict`: **valid, rc=0**

Reproduced independently on the clean archive; matches the builder's counts.

### Defect 1 unchanged

`unknown_kind` reaches `previous_error` via `subtask.error` (plan_orchestrator.py:632)
and is refused before dispatch. Not re-litigated — it passed at bd9f604 and the
F1 commit does not touch it.

## Findings

### F1 (minor) — The spec names four not-started shapes; only one has a scenario

The requirement at `spec.md:59-60` defines not-started as: no directive id,
`directive_never_started`, raised (`DISPATCH_ERROR`), or refused before dispatch
(`unknown_kind`). The code now handles all of these (plus `bad_directive` and
`no question given`).

But the delta carries only two scenarios for this requirement:
- "Rejected dispatch cannot complete a plan" — covers `directive_never_started`
- "One directive started" — covers the mixed case

There is **no scenario** for the raised path (`DISPATCH_ERROR`), which is the
one the fix was specifically extended to cover, and no scenario for the
pre-dispatch refusal. The code and its unit tests cover them (per-marker
mutation proves it), but the spec's scenarios do not.

This is not a code defect. It is the same class as `fee4e53`: a delta claiming
coverage its scenarios don't demonstrate. A future reader implementing this
requirement from the spec alone would not know the raised path is in scope.

**Suggested fix (not required to merge):** add one scenario for the raised
dispatch — GIVEN the only directive raises, WHEN the attempt finishes, THEN the
subtask is not complete and the attempt fails with the dispatch error. That is
the shape the 11-13 defect takes through `dispatch_error`, and it is the one
worth pinning.

### F2 (trivial) — Stale line number cited in three places

The `DISPATCH_ERROR` emitter is at **`plan_orchestrator.py:665`**
(`last_result = f"DISPATCH_ERROR: {e}"`). Three places cite `:644`, which is
`dispatched = 0`:

- `plan_orchestrator.py:491` (comment)
- `test_dispatch_must_start.py:240` (docstring)
- the builder's handoff message

The marker table line (`:500`) is correct; only the *emitter* citation is wrong.
Trivial, but a comment that points at the wrong line is how the next reader
wastes a turn.

## Notes

- `bad_directive` and `no question given` are matched as bare substrings. I
  checked this does not invite false positives: no result string in the suite
  contains those phrases except the `FAILED` emitters. If a future emitter ever
  emits "no question given" in a success path it would misclassify, but no such
  path exists today.
- `task_d_fixes_test.py` hangs at 2d on a real Ollama call. I did **not** run
  it (it needs localhost:11434 and this seat has no network to it). The builder
  states it hangs identically on clean 206c997. I have not independently
  confirmed that claim; treating it as the builder's, not verified by me.
- qcode produced no patch in ~6 min. Recorded, not acted on.

## Provenance

- Clean archive of `4f8ceb97df5d064d92a9a5ff4b53b3b289efc5cc`
- Function tested by direct import (agent dir on sys.path; `api` import needs it)
- Mutations: anchor asserted unique before each, file restored from a saved copy,
  `git diff --stat 4f8ceb9` empty after restore
- All suites run via file, rc captured directly (no pipe) — see memory note
  "a pipe reports the last command's status"

# Review: plan call truncated-not-parsed — `9903d25`

**Rev:** `9903d25` (on `53cb99a`, branch `ship-ca27-harness`)
**Row:** `qitem-20261120215725-9d8c85f2bb7efd12` (builder)
**Spec:** `openspec/changes/ai-written-scripts/specs/bot-coded-agents/spec.md`, delta +44 lines
**Verdict:** **PASS with one required fix** — the behaviour is correct and every claim in the
commit body that I checked holds; one duplicated constant must go, because it makes the
budget's own regression test dead in the place a future editor will touch.

---

## What holds, executed at a clean `git archive 9903d25`

- **Length stop is decided before the parse.** The guard sits at `l3_planner.py:522-532`,
  before `_strip_codefence(answer_text(body))` at `:533`, so a reply cut mid-object raises
  `TruncatedAnswer` instead of falling into `json.loads`. It also precedes `answer_text`,
  which matters for the reason the commit gives: `config.answer_text` raises only on EMPTY
  content, so a partial object would never have reached that guard.
- **The guard is load-bearing.** Mutant: delete `:522-532`. Exactly two tests red —
  `test_a_partial_plan_cut_by_the_limit_is_not_parsed` and
  `test_a_complete_plan_that_merely_says_length_is_still_refused`. Nothing else moves.
- **The orchestrator catch is load-bearing.** Mutant: `except (PlanValidationError,
  l3_planner.TruncatedAnswer)` → `except PlanValidationError`. Reds
  `test_a_truncated_plan_yields_a_failed_plan_not_an_exception` with
  `config.TruncatedAnswer: cut off (done_reason=length)` escaping as `RuntimeError`. The
  commit's reason for adding the clause is accurate: `TruncatedAnswer` subclasses
  `RuntimeError` (`config.py:142`), not `ValueError`, so it passed both `except` arms here
  and left through `agent.py:1373`'s `except Exception` as "orchestrator crashed".
- **Q1 — the timeout fits 4096.** `_OLLAMA_TIMEOUT = 420.0` (`l3_planner.py:69`). At the
  measured 32 tok/s, 4096 tokens is ~128 s; plus the 68 s cold-load ceiling that is ~196 s,
  against 420 s. At 37 tok/s, ~111 s + 68 s = ~179 s. The lead's ~200 s estimate is correct.
- **Q2 — no load option is sent.** The plan request body is `format`, `stream`, `messages`,
  `options{temperature, num_predict}`. `num_ctx` does not occur anywhere in `l3_planner.py`
  at this rev; neither does `keep_alive` or any other load field.
- **Q3 — the replaced test still tests something.** The old
  `assertEqual(num_predict, 1024)` now reads the wire value and compares it to
  `l3_planner._PLAN_NUM_PREDICT`, plus a genuine
  `assertNotEqual(_PLAN_NUM_PREDICT, _SCRIPT_NUM_PREDICT)`. The second is real and worth
  keeping. The first is worth less than it looks (see F1).
- **Spec validates on its own bytes.** `openspec validate ai-written-scripts --strict` rc=0,
  run in the archive after confirming the file's sha256 equals
  `git show 9903d25:openspec/changes/ai-written-scripts/specs/bot-coded-agents/spec.md`
  (both `a0f9f50f...`).
- **Suites:** `test_l3_script_path` 82 OK rc=0, `test_planner_script_output` 4 OK rc=0.

## F1 (required) — `_PLAN_NUM_PREDICT` is defined twice; the second is dead

```python
1355:  _PLAN_NUM_PREDICT = 4096     # the one that binds
...
1390:  _PLAN_NUM_PREDICT = 4096     # identical; shadows nothing, because it agrees
```

Both are module-level literals in the same file, after the same neighbours
(`_SCRIPT_NUM_PREDICT`, `_CLASSIFY_NUM_PREDICT`), carrying different comment blocks. The
second — the one with the six-row measurement table and the "four times the largest plan
seen" rationale — is the one a future editor will find and edit. Rebinding it there changes
nothing.

Measured, not argued:

| Mutant | Result |
|---|---|
| `:1390` → 1024, `:1355` untouched | **82 OK** |
| `:1390` deleted, `:1355` → 1024 | 1 red: `test_the_plan_budget_clears_the_observed_ceiling` |
| `:1390` deleted, `:1355` left at 4096 | 82 OK (duplicate removal alone is inert) |

So the assertion itself is sound and the duplicate alone is the defect: **the guard test is
inert against the edit direction the file invites.** Fix: delete one of the two definitions
and keep one comment block. I have no preference which table survives — the `:1367-1390` one
is the fuller, and the `:1346-1355` one names the call's separability; whichever goes, the
survivor should carry both points.

Nothing else in the diff needs to change for this.

## Recorded, non-blocking

**P-1 — the spec's third scenario quantifies over a past event.** "The budget was measured
against the deployed model" requires that "the recorded measurement MUST say how many calls
were cut off at the previous budget". No test can fail that; the measurement lives in the
commit message and the source comment (4 of 6, stated in both). The first bullet —
`_PLAN_NUM_PREDICT` exceeding the largest observed `eval_count` (2396) — *is* tested and
falsifiable. The second bullet is documentation wearing a scenario's clothes. Either pin it
to an artefact a test can read, or move it out of the scenario. Not a hold: the requirement
it carries is satisfied by the prose.

**P-2 — a doubled budget is not a fixed failure.** The new log line says raising
`_PLAN_NUM_PREDICT` "does not make this answer usable", which is true of the reply in hand
and false as a general claim — this commit exists precisely because doubling the budget
turned 4-of-6 cut-offs into 3-of-3 completions. The operator reading that line mid-incident
could conclude no budget change is worth trying. A wording matter for whoever next touches
the line; the behaviour is right.

**P-3 — carry-forward, unchanged by this rev.** The plan call's `_strip_codefence` now
receives `body` rather than the `answer_text` result hoisted into a local — same call, same
argument, no behavioural change. Noted only so the diff line is not mistaken for a change.

## Not disputed

- The commit's measurement figures (4/6 at 1024; `eval_count` 698/959/2396 at 4096) are the
  builder's, taken through the test gateway. **This review does not re-measure them and does
  not depend on them** — every claim above is about the code's structure and its tests. The
  lead is checking those numbers in the trial, which is the right place for them.
- No probe was sent to `ollama-l3` for this review.

Nothing built or deployed by this review.

# Re-review: plan budget duplicate removed — `62f44a0`

**Rev:** `62f44a0` (child of `9903d25`, verified by `git rev-list --parents`)
**Prior:** review `843e4f4` — PASS with one required fix (F1) and two non-blocking notes
**Verdict:** **PASS** — F1, P-1 and P-2 all closed; no behaviour change; the record
correction the lead asked for is below.

---

## F1 closed — and the builder's account of which definition survived is wrong

The lead flagged that the builder's account ("the SECOND definition was the live one")
contradicts my measurement. **My original measurement stands. The builder's sentence is
wrong; its fix is right.**

Measured at `9903d25`: a module-level assignment binds at execution time in file order, so
the later definition wins. `:1390` (the block with the per-call table) shadowed `:1355`.

What the fix did, read off the diff:

- **Deleted** `:1346-1355` — the shorter block reading "Measured 2026-11-20 22:0xZ … at 1024,
  4 of 6 calls were cut off". This was the **LIVE** definition.
- **Kept** `:1367-1390` — the six-row per-call table. This was the **DEAD** one, and it
  inherited the name.

So the surviving definition was the dead copy, not the live one. That is the *opposite* of
what the builder's sentence says, and it is also the better outcome: the surviving block is
the fuller one (table plus folded-in 4x thinking swing, the `eval_count` 2396 clear, the
6144-footprint note and the separability sentence), so no rationale was lost.

**Both consequences verified, not assumed:**

| Check | Result |
|---|---|
| `grep -cE "^_PLAN_NUM_PREDICT *=" l3_planner.py` | **1**, at `:1385` |
| surviving value | `4096` |
| value on the wire, captured from `call_plan`'s real request | `num_predict: 4096` |
| request body keys | `format, messages, model, options, stream, think`; `options = {num_predict, temperature}` — no load option |
| the mutant that used to survive (4096 → 1024) | **1 red**: `test_the_plan_budget_clears_the_observed_ceiling` |

That last row is the point of F1: the edit direction the file invites is now caught. My
finding was that the test was inert against it; it no longer is.

## P-1 closed

The untestable bullet is gone from `specs/bot-coded-agents/spec.md`:
`AND the recorded measurement MUST say how many calls were cut off at the previous budget`
(2 lines removed, nothing else). The testable bullet —
`THEN it MUST exceed the largest eval_count observed at a higher budget` — remains and is
still the assertion `test_the_plan_budget_clears_the_observed_ceiling` makes. No other
requirement or scenario shifted.

## P-2 closed

The warning now reads "…and is unusable as it stands; the budget was %d". It describes the
reply in hand and names the budget as context, so it no longer tells an operator mid-incident
that no budget change is worth trying. Behaviour inside the branch is unchanged: same
condition, same `TruncatedAnswer`, same `done_reason`/`eval_count` in the exception text.

## No behaviour change — checked, not accepted

The diff touches two files: `agent/l3_planner.py` (29 lines, net −7) and the spec (2 lines
removed). The only executable change in `l3_planner.py` is the deleted duplicate constant,
which was dead by construction. The guard condition, the raise, the exception type and the
request body are identical to `9903d25`.

## Suites

- `test_l3_script_path` + `test_planner_script_output` + `test_agent_script_branch`:
  **138 OK, rc=0**.
- `python3 -m unittest discover -p "test_*.py"`: **402 tests, 30 failures + 1 error.**
  I diffed the failing-test names between this rev and its parent rather than reading the
  count: **zero failures are new**, and two errors present at the parent are gone
  (`test_configmap_matches_the_script`, `test_the_configmap_is_not_mounted_yet` — flaky on
  environment, not fixed by this diff). The residue is the known pre-existing environment
  breakage (`uvicorn`/`dashboard`, `psycopg2`, `pydantic`), none of it in the modules this
  rev touches.
- `openspec validate ai-written-scripts --strict`: rc=0, run in the archive after the spec's
  sha256 matched `git show 62f44a0:` (both `30161b18...`).

## For the record

The builder's F1 sentence is a mis-description of a correct change. I am not asking for a
rewrite of a commit message; I am asking that the queue note or the lead's trial log not
carry "the second definition was the live one" forward as fact, because the next person to
read the file will find a single definition whose history says the opposite.

Nothing built or deployed by this review. No probe sent to `ollama-l3`.

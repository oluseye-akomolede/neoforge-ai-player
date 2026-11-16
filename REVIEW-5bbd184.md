# Review: 5bbd184 — record what planner-prompt-declines actually shipped

**Verdict: PASS to merge.** One finding on the text, no code impact, fixable in place.

Rev: `5bbd184`, on `ship-ca27-harness` rebased onto `main` = `4e47b41`.
Scope confirmed: one commit, `tasks.md` only, 54+/10-.
`git diff --stat main 5bbd184 -- agent/l3_planner.py agent/tests/test_planner_prompts.py` is empty.

## The question asked: is any DROPPED item actually shipped?

**No. All five are correctly dropped.** Checked against the shipped `_PLAN_SYSTEM_PROMPT`
on `main` (`agent/l3_planner.py`, 111 lines, 5678 chars), read in full rather than grepped:

| Task | Claimed dropped | Present on main? |
|---|---|---|
| 2.1 chat-is-an-action rule | `grep -c "Chat is an action"` = 0 | absent |
| 2.2 transient-vs-impossible rule | `grep -c "precondition"` = 0 | absent |
| 2.2a planning-around clause | `grep -c "Planning around"` = 0 | absent |
| 2.4 tests pinning the added rules | `test_planner_prompts.py:51-52` hold the **inverse** `assertNotIn` guards | absent by construction |
| 3.1 the two decline-precision bullets in the delta | delta carries only the live rule + clarify/refuse shapes | absent |

The shipped prompt does carry the *preserved* rules the tasks say survived (2.3): the
moon refusal, the bedrock-simultaneity refusal, and the "go get some stuff" clarify are
all present, and "A fabricated plan is worse than a refusal" is still there.

## Every cited check reproduces on main 4e47b41

    If truly impossible = 0        Chat is an action = 0        precondition = 0
    Planning around = 0            by category = 0             ALWAYS a precondition = 0
    :973 = "Output ONLY a single replacement subtask JSON (no prose, no fences)"
    :1035 = if isinstance(data, dict) and data.get("error"):
    test:69 = self.assertNotIn("If truly impossible", text)
    test:51-52 = assertNotIn(ALWAYS a precondition), assertNotIn(precondition ... YET)

## 3.3 "Partial" is accurate

All four scenarios it claims shipped exist exactly once on `main`; none of the five
original names exists:

    Correct refusal of an impossible ask            1
    Correct clarify of a vague ask                  1
    Replan is not offered a refusal shape           1
    A refusal-shaped replan answer fails validation 1
    false-decline-capability / -transient-state /
    correct-refusal-preserved / correct-clarify-preserved /
    replan-returns-subtask-not-error                0

## Finding F1 — 4.4 is ticked `[x]` while recording that its own condition fired

4.4 reads: "If exec drops below 25/25, say so plainly and propose a revert rather than
defending the change." It is ticked, and its note says **"Exec 24/25 is below the 25
baseline"** — i.e. the trigger condition was met and no revert was proposed in the
note. The correct outcome is stated (rework not shipped, `ca27b6e` shipped instead),
but the action the task names ("propose a revert") did not happen and the tick
asserts it did.

This is a small text defect with a specific failure mode: a ticked 4.4 is the line a
later reader will cite to argue the revert rule was exercised. Mark it `[~] N/A` with
the reason — the revert question was answered upstream by not shipping the rework —
rather than `[x]`.

Note the ordering ambiguity this leans on: 4.3 records the lead's figures in the order
"exec/plan/replan" as replan-only **25/16/25** and rework **24/17/25**, so "24" is exec.
The builder flags in-commit that the reading is theirs and the figures the lead's,
which is the right hedge. It does not change F1, because 4.4's own note states 24 < 25.

## Non-findings checked and cleared

- 3.2 is ticked, and the delta does contain both claims it names ("Replan is not
  offered a refusal shape" asserts the prompt must require a single replacement
  subtask; "A refusal-shaped replan answer fails validation" covers the
  `PlanValidationError` path). Tick justified.
- 1.3's `data.get("error")` guard is present at `:1035`.
- Sources: figures in section 4 are attributed to the lead, not restated as the
  builder's measurements. That is the correct handling.

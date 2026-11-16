# Review: adee29a + 8d38ee5 — F1 fixed, and a licence correctly refused

**Verdict: PASS. Both commits are `tasks.md` only.**

`adee29a`: 6+/4-. `8d38ee5`: 4+/2-.
`git diff --stat main 8d38ee5 -- agent/l3_planner.py agent/tests/test_planner_prompts.py` empty.
`openspec validate planner-prompt-declines --strict` -> "Change is valid", rc=0, at `8d38ee5`.

## F1 is fixed correctly

`4.4` is now `[~] 4.4 N/A`, note opening with **"NOT EXERCISED, so not ticked"**, and it
states the thing I was actually worried about: exec 24/25 < 25, the rework never
shipped, so a revert would have reverted nothing.

Two things I checked rather than accepted:

- `[~]` is an established status in this repo, not an invention — five uses, including
  one in an archived change (`2026-11-10-bound-http-api-joins`).
- The note's supporting figure `66/75 vs 66/75` is consistent across all six places it
  appears in the file, and 75 = N=25 x 3 kinds matches the harness's own documented N
  (`evals/job-evals.yaml:159`). No arithmetic drift.

`N/A` and `NOT EXERCISED` do describe two different things — "cannot apply" versus "did
not fire". The note resolves it correctly (the task's condition did fire; the action
became moot upstream), so this is a wording preference, not a defect. No change wanted.

## 8d38ee5 — the ordering attribution

The builder took a licence I explicitly left open and declined it. I had said I would
not relitigate the exec/plan/replan ordering; they reasoned that "would not relitigate"
is not "was correct to leave as written", and they were right: the file had
`(exec/plan/replan)` presenting as the lead's words an ordering the lead did not give.

The file now says the labels are the builder's inference from the baseline line at the
top of the same 4.3 entry. **That cross-reference resolves**: line 93 of the same file
reads `11-14 baseline: exec 25/25, plan 19/25, replan 21/25`, so the inference has a
visible, local basis rather than a remembered one. This is strictly better sourcing than
what I reviewed.

## Non-finding

`"The reading of which figure is exec is the builder's; the figures are the lead's."`
now appears in 4.4 as well as in the newly-expanded 4.3 attribution. Slight repetition;
harmless, and I would rather have an attribution stated twice than once.

## Remaining ticks checked

The builder's claim that no other tick asserts an unperformed action holds on my read:
4.5 is a negative the builder can attest (no image built), 4.1 and 4.2 are facts about
`main` and about who ran the Job. 4.3 is a report of the lead's figures, attributed.

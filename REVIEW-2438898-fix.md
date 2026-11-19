# Review: 0575b40 (fixes F1/F2 from REVIEW-2438898)

**Verdict: PASS.** Verified from git archive 0575b40, not a worktree.

## What the fix does
`_new_goal_id(sender, text)` returns `chat:{sender}:{text[:40]}#{seq}` with a
monotonic `_script_hold_seq`. Both accept sites (:675, :878) call it; the
`text[:40]` construction is gone from both. The readable prefix is kept for
logs; the `#<seq>` suffix is the identity.

## F1 closed - proven, not accepted
- Baseline re-run: 104/104 (test_agent_script_branch 40, test_script_tick 37,
  test_scout_script 27), all rc=0.
- Mutant: mutated the helper back to `f"chat:{sender}:{text[:40]}"` (anchor
  count asserted == 1 before mutating). Suite goes 40 tests -> 2 failures:
  `test_two_goals_sharing_a_prefix_get_distinct_ids` and
  `test_a_finished_goal_does_not_release_a_running_goal_with_the_same_prefix`.
  These are exactly the two tests that did not exist in 2438898, and they redden
  on precisely the defect. Restored, green again.
- F2 closed: both new tests build ids through `_new_goal_id`, not by hand.

## Edge cases probed (no defect found)
- Forged-id collision: the `#<seq>` is always the final component, so a `#` in
  the sender or the text cannot forge a match. `("Steve","build a wall")` vs
  `("Steve#1","")` -> distinct.
- Duplicate input: 50 identical `(sender,text)` calls -> 50 distinct ids.
- Monotonic and never reset (only writes are :264 init and :1302-1303).

## The "single writer, no lock" claim - checked, holds
Both callers are in `_maybe_plan`, whose sole call site is :3094 on the agent
loop thread with no Thread target. So the read-modify-write is single-writer and
the missing lock is correct here, unlike the `_goal_generation` concern in
REVIEW-8a1f657, which concerned the orchestrator spawn paths (a different
object, different threads) and does not apply to id minting.

## Note for the TEST gate
This is a review of the commit. The real-agent-loop run on TEST remains the
lead's gate and is not covered here.

Nothing pushed, nothing applied.

# Review: acf051e (the hold must not cancel the goal it holds for)

**Code: PASS. Spec: NOT YET** (stale citations + a spliced duplicate paragraph).
Verified from git archive acf051e.

## The code fix is right and the removal is complete
`_begin_script_hold` no longer calls `_cancel_orchestrator`. Grep confirms the
only `_cancel_orchestrator` call sites are :340 (reset) and :520 (nav shortcut);
the hold has none. The docstring now says why, with the TEST timestamps.

Baseline: 77/77 agent suites rc=0 (test_agent_script_branch 40, test_script_tick 37).

Mutant: restored `self._cancel_orchestrator(f"held by goal {goal_id}")` at the
anchor (count asserted == 1). Suite 40 -> exactly 2 failures:
  test_a_held_goal_runs_its_real_orchestrator_to_completion
  test_beginning_a_hold_does_not_cancel_anything
Nothing else moved, and both fail on the substantive assertion (they drive the
real `_run_orchestrator` start), not on setup. This is the test shape the
offline suite lacked, and it is the right shape.

## S1 (blocking): the spec rewrite left the old sentence in place
The paragraph now ends its new text with:
  "... A hold is therefore its own state, not this latch - and must not set
   this latch at all."
immediately followed by the un-deleted original opener:
  "A hold therefore MUST be its own state, not this latch, and the resume MUST
   consult the holding goal's own outcome rather than a bare flag. The state MUST
   identify ..."
So the conclusion is stated twice in consecutive sentences and the new text is
spliced mid-paragraph. No behaviour is wrong, but this is the normative
requirement text; a duplicated conclusion reads as two competing rules. Delete
the old opener and join the remainder onto the rewritten paragraph.

## S2 (blocking): seven stale citations, including the two that carry the argument
The requirement's whole case rests on call order, and both order citations are
wrong at this rev. Verified by printing each line from `acf051e:agent/agent.py`:

  cited      actual    what is actually at the cited line
  :3074      :3098     "a comment about M3-1c" / actual: self._maybe_plan(new_msgs)
  :3082      :3106     "return self._script_tick" / actual: if self._run_script_tick():
  :684       :678-685  ")" / actual: t = threading.Thread(target=self._run_orchestrator, ...)
  :298       :340      "self._chat_thread.start()" / actual: cancel reason="reset"
  :471       :520      (nav) actual: cancel reason=f"nav shortcut: ..."
  :1438      :1584     "except Exception:" / actual: if self._orch_cancel is cancel_event:

The ORDER CLAIM ITSELF IS TRUE - :3098 `_maybe_plan` precedes :3106
`_run_script_tick`. Only the numbers are stale.

The pattern is diagnostic and worth naming: the two citations this commit
introduced fresh are EXACT (`:1281` `_orch_stop_pending = True`, `:1558`
`if getattr(self, "_orch_stop_pending", False)`), while every citation inherited
from the earlier text is stale by a different amount (+24, -6, +42, +49, +146).
So this is not one insertion offset - it is that the new claims were checked
against this rev and the carried-over ones were never re-checked. The fix is a
sweep of every l.NNN in the holding requirement, not a global shift.

## S3 (minor): the "carry cause and identity" paragraph now argues against itself
It says a hold must not set the latch, then in the same breath justifies the
separate-state requirement by what happened "before the developer-test fix". The
counterfactual is useful history, but it is in a MUST paragraph. Consider moving
the post-mortem to the task text and keeping the requirement normative.

## On the substance of the reversal
The abort wording was wrong and the builder is right to have changed it: the run
spawned for the goal being held IS the goal, so cancelling it cancels the thing
the hold exists to wait for. I reviewed and PASSed that abort wording twice
(5ba8be6, fca4c6b) - I checked that the abort MECHANISM worked and never asked
whether aborting was the right action. The mechanism was correct and the action
was wrong, and my reviews did not separate those. Recorded.

Not covered: the live TEST run, which is the lead's gate.

Nothing pushed, nothing applied.

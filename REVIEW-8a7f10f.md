# Review: 8a7f10f (S1/S2/S3 fixes + the 9.4 record edit)

**Verdict: PASS.** Verified from git archive 8a7f10f. Doc-only (spec.md + tasks.md).

## S1 closed
One conclusion remains, at spec.md:792 ("A hold MUST therefore be its own state,
not this latch ..."); the old opener is gone and the remainder is joined. My first
grep for the duplicate returned 0, which proved nothing because my pattern did not
match the joined wording - I re-grepped for the content and confirmed one
occurrence, not a string count.

## S2 closed - all eleven citations verified, not accepted
Printed each from `8a7f10f:agent/agent.py`:
  :2258 interrupted_by_chat reason      :2971 "interrupted_by_chat" in str(result)
  :3098 _maybe_plan(new_msgs)           :3106 if self._run_script_tick():
  :678  t = threading.Thread(           :520  nav shortcut cancel
  :340  reset cancel                    :1281 _orch_stop_pending = True
  :1558 getattr(..., "_orch_stop_pending")   :1559 _orch_stop_pending = False
  :1584 if self._orch_cancel is cancel_event
All correct. The order claim holds (:3098 precedes :3106). They found four
stale citations I had not listed (:2197, :2804, :473, :1413) and swept those too.

## S3 closed
The "before the developer-test fix" post-mortem is out of the MUST paragraph and
into the 9.8 task record (tasks.md:747-760).

## The 9.4 edit - no delta needed, and here is the check
They flagged it for my judgement. It is in tasks.md ONLY (:422-423), adding "The
gate therefore keys on `directive.status`, and on `phase` idle only for the
never-run case." That is a task record, not requirement text, so it needs no
spec delta. It is also not new behaviour - task 9.4's own title at :406 already
reads "keys on directive status, not on the phase", and the body already lists
the three terminal statuses. The added sentence restates the title.
Verified against the code rather than the prose: scout.js:39-44 keys on
ternary directive.status terminal via TERMINAL_STATUSES, and :44 on
progress.phase === "idle". The sentence is accurate.

## Suite
77/77 rc=0 (test_agent_script_branch 40, test_script_tick 37).
openspec validate coded-agents --strict: "Change 'coded-agents' is valid", rc=0
(read via PIPESTATUS, not the pipe footer).

## Scope of this PASS
Spec and task text only. The live TEST run remains the lead's gate and I hold no
live evidence.

Nothing pushed, nothing applied.

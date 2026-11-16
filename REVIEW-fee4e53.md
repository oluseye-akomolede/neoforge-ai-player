Reviewed fee4e53 (ship-ca27-harness). Reviewer: minecraft-reviewer. Row qitem-20261116005138-1f290b9496b7e23f.

# fee4e53

## Structural claims, independently re-derived (all hold)
- parent of fee4e53 = ca27b6e3ab45
- `git diff ca27b6e fee4e53` over the 4 rework files: empty
- `git diff --name-only 807b6f1 fee4e53`: exactly those 4 files
- l3_planner.py sha256 = 797739220453a544 at BOTH ca27b6e and fee4e53
- _PLAN_SYSTEM_PROMPT body sha e781af2d85826990 at 9e656b3, ca27b6e AND fee4e53;
  b17b0e95a029a9a9 at 807b6f1. So fee4e53 ships ca27b6e's plan prompt and not the rework's.

## (1) rework text in run.py / test_run.py / case_labels.json -- 0 hits
True, and I also recorded WHY it is a weak test: run.py imports l3_planner at line 497
rather than embedding prompt text, so a textual grep for prompt prose is zero for
almost any prompt. The load-bearing check is the prompt hash above and the test at
test_planner_prompts.py:43, which pins the rework's rules as ABSENT. Both hold.

## (2) suites on a clean `git archive` of fee4e53 (nice -n 19, bounded)
- evals: 122 tests OK
- planner prompts (from agent/): 8 tests OK
- check_apply_matches_job.py: rc=0

## (3) openspec -- one finding
`openspec validate --strict`: valid.

FINDING: the delta describes rules fee4e53 does NOT ship, as live.
`openspec/changes/planner-prompt-declines/specs/l3-spec-driven-planning/spec.md`
MODIFIES "Phase 1 -- Planning Call" to REQUIRE:
  - :17-19 transient-vs-impossibility distinction ("a state that does not hold YET
    MUST be planned around")
  - :22-24 the "obtaining the missing precondition ... MUST NOT substitute" rule
  - :44-49 "Missing capability as a directive is not missing capability"
and to add scenarios "Transient state is planned around, not declined" and
"Missing capability as a directive...".

Cross-checked against the shipped prompt at fee4e53: the word "transient" does not
appear in _PLAN_SYSTEM_PROMPT, nor does "precondition", nor "missing information",
nor any chat/speech rule (only "directives" as a code-machinery noun at :5/:127).
The rework commit fdca63e is what introduced that language; the delta was carried
forward verbatim at ca27b6e/fee4e53.

This is the split failing at the spec layer. The code half of the split is guarded
(test_planner_prompts.py:43 asserts the rework rules are absent) and the spec half
is not: the same commit that pins the rules ABSENT from the prompt asserts them
PRESENT in the spec. Anyone reading openspec/ on main after this lands is told the
product plans around transient state and treats speech-as-directive as covered;
it does neither. That is the delta-gates-the-live-product rule (OpenSpec is the
source of truth) running backwards.

NOT fixed by: dropping the 4 files. The delta must be reverted to its ca27b6e-state
plan section -- i.e. MODIFY only what ca27b6e's prompt actually does, which for the
plan half is: no plan-prompt change ships at all, only the replan change. Suggested
smallest correct shape: strip the Phase 1 MODIFIED requirement down to the replan
prompt's own content, or narrow this change to "Replan on Repeated Failure" only.

## Honest limits
- Neither of the two spec scenarios above has a backing test on this rev, so nothing
  in the suite can notice the delta drifting ahead of the prompt -- the absence is
  invisible to CI by construction.
- I did not run the eval Job (no cluster actions).

VERDICT: NOT PASS -- on finding (3) only. (1) and (2) are clean.

# Tasks

## 1. Prompt: replan has no refusal path

- [x] 1.1 Remove the `If truly impossible, return: {"error": ...}` line from
      `_REPLAN_SYSTEM_PROMPT` in `agent/l3_planner.py`.
      Verified on main `4e47b41`: `grep -c "If truly impossible"
      agent/l3_planner.py` = 0.
- [x] 1.2 Replace it with an explicit instruction that the response MUST be a
      single replacement subtask object, and that a failed subtask is not an
      impossible task — revise the approach instead of declining.
      Verified on main `4e47b41`: `agent/l3_planner.py:973` "Output ONLY a
      single replacement subtask JSON (no prose, no fences)".
- [x] 1.3 Leave the `{"error": ...}` handling in `call_replan` intact: if a model
      returns an error object anyway, `PlanValidationError` still fires and the
      bounded-replan rule still ends in `status = failed`. The prompt stops
      inviting the answer; the guard against it stays.
      Verified on main `4e47b41`: `agent/l3_planner.py:1035` still tests
      `if isinstance(data, dict) and data.get("error")`.
- [x] 1.4 Add a test asserting `_REPLAN_SYSTEM_PROMPT` does not offer an error
      object as an output shape (guards the regression that produced 4 of the
      4 replan failures).
      Verified on main `4e47b41`: `agent/tests/test_planner_prompts.py:69`
      `self.assertNotIn("If truly impossible", text)`.

## 2. Prompt: narrow the decline predicate in plan

- [ ] 2.1 Add a rule that the bot can communicate with the player outside the
      directive list, so "I have no chat directive" is not grounds to refuse a
      task whose goal is to report an outcome.
      DROPPED 11-16: plan-rule rework measured no gain (66 vs 66/75, same cases and harness); not shipped. Verified on main `4e47b41`: `grep -c "Chat is an action"
      agent/l3_planner.py` = 0.
- [ ] 2.2 Add a rule distinguishing transient state from impossibility: a
      precondition that does not hold *yet* (empty inventory, not in the right
      dimension, tool not held) is planned around; only world facts (missing
      dimension, uncraftable item, unbreakable block, two mutually exclusive
      simultaneous actions) justify `refuse`.
      DROPPED 11-16: plan-rule rework measured no gain (66 vs 66/75, same cases and harness); not shipped. Verified on main `4e47b41`: `grep -c "precondition"
      agent/l3_planner.py` = 0.
- [ ] 2.2a In the same rule, state that planning around means obtaining the
      missing precondition and then completing the stated task — never
      substituting a different, doable-sounding task, which the
      clarify-or-refuse requirement already forbids.
      DROPPED 11-16: plan-rule rework measured no gain (66 vs 66/75, same cases and harness); not shipped.
- [x] 2.3 Keep both existing decline examples (moon; simultaneity) and both
      clarify examples in the prompt. Do not reword them into softness.
      Verified on main `4e47b41`: the prompt still carries "fly to the moon"
      → refuse, "dig to bedrock at the same time as X" → refuse, and
      "go get some stuff" → clarify.
- [ ] 2.4 Add tests pinning the two added rules' presence in
      `_PLAN_SYSTEM_PROMPT`, and a test asserting the correct-refusal examples
      are still present.
      DROPPED 11-16: plan-rule rework measured no gain (66 vs 66/75, same cases and harness); not shipped. Main instead carries the inverse guards from the same change:
      `agent/tests/test_planner_prompts.py:51-52`
      `assertNotIn("Bot state is ALWAYS a precondition", ...)` and
      `assertNotIn("precondition that does not hold YET", ...)`.

## 3. Spec delta

- [ ] 3.1 `specs/l3-spec-driven-planning/spec.md`: MODIFIED *Phase 1 — Planning
      Call* — add the two decline-precision bullets to the prompt's MUST
      instruct list.
      DROPPED 11-16: plan-rule rework measured no gain (66 vs 66/75, same cases and harness); not shipped. The delta keeps only the live prompt's rule (a task it cannot carry
      out is declined rather than silently replaced) plus the clarify/refuse
      shapes.
- [x] 3.2 MODIFIED *Replan on Repeated Failure* — state that the replan prompt
      MUST NOT offer a refusal/error output shape, and that a replan response
      that is not a replacement subtask is a validation failure, not a decline.
- [x] 3.3 Scenarios: false-decline-capability, false-decline-transient-state,
      correct-refusal-preserved, correct-clarify-preserved, replan-returns-
      subtask-not-error.
      Partial. The two false-decline scenarios are DROPPED 11-16 with the
      plan-rule rework above; they cannot exist without the rules. Shipped
      instead: "Correct refusal of an impossible ask" and "Correct clarify of
      a vague ask" (preserved behaviour), "Replan is not offered a refusal
      shape" and "A refusal-shaped replan answer fails validation".
      Verified by listing `#### Scenario:` in the change's spec delta.
- [x] 3.4 `openspec validate --strict` clean.
      Verified: `openspec validate planner-prompt-declines --strict` →
      "Change 'planner-prompt-declines' is valid", rc=0. Bare `--strict`
      validates nothing (it prints "Nothing to validate" and exits 1), so the
      change is named explicitly.

## 4. Hand back to the lead

- [x] 4.1 Report the commit sha and the diff summary.
      ca27b6e, merged to main as 4e47b41 ("Merge ship-ca27-harness: replan fix
      (ca27b6e) + reviewed eval harness").
- [x] 4.2 The lead runs the eval Job think-off; builder does not run cluster
      Jobs.
      The lead ran it; the builder ran nothing on the cluster.
- [x] 4.3 Report before/after per kind **from the Job log only**, against the
      11-14 baseline: exec 25/25, plan 19/25, replan 21/25.
      The lead's 11-16 figures, in the order the lead gave them
      (exec/plan/replan): replan-only 25/16/25, plan-rule rework 24/17/25.
      Image 2914fb85 to test 11-15 18:06Z, prod 11-16 04:13Z. These are the
      lead's recorded numbers; the builder did not re-measure them.
- [~] 4.4 N/A If exec drops below 25/25, say so plainly and propose a revert rather
      than defending the change.
      NOT EXERCISED, so not ticked: exec 24/25 is below the 25 baseline, but the
      rework was never shipped. The lead measured it (66/75 vs 66/75) and decided
      not to ship before any revert question arose; a revert would have reverted
      nothing. No revert was proposed by the builder, and none was needed. The
      reading of which figure is exec is the builder's; the figures are the lead's.
- [x] 4.5 No image build until the lead asks.
      No image was built by the builder.

# Tasks

## 1. Prompt: replan has no refusal path

- [x] 1.1 Remove the `If truly impossible, return: {"error": ...}` line from
      `_REPLAN_SYSTEM_PROMPT` in `agent/l3_planner.py`.
- [x] 1.2 Replace it with an explicit instruction that the response MUST be a
      single replacement subtask object, and that a failed subtask is not an
      impossible task — revise the approach instead of declining.
- [x] 1.3 Leave the `{"error": ...}` handling in `call_replan` intact: if a model
      returns an error object anyway, `PlanValidationError` still fires and the
      bounded-replan rule still ends in `status = failed`. The prompt stops
      inviting the answer; the guard against it stays.
- [x] 1.4 Add a test asserting `_REPLAN_SYSTEM_PROMPT` does not offer an error
      object as an output shape (guards the regression that produced 4 of the
      4 replan failures).

## 2. Prompt: narrow the decline predicate in plan

- [x] 2.1 Add a rule that the bot can communicate with the player outside the
      directive list, so "I have no chat directive" is not grounds to refuse a
      task whose goal is to report an outcome.
- [x] 2.2 Add a rule distinguishing transient state from impossibility: a
      precondition that does not hold *yet* (empty inventory, not in the right
      dimension, tool not held) is planned around; only world facts (missing
      dimension, uncraftable item, unbreakable block, two mutually exclusive
      simultaneous actions) justify `refuse`.
- [x] 2.2a In the same rule, state that planning around means obtaining the
      missing precondition and then completing the stated task — never
      substituting a different, doable-sounding task, which the
      clarify-or-refuse requirement already forbids.
- [x] 2.3 Keep both existing decline examples (moon; simultaneity) and both
      clarify examples in the prompt. Do not reword them into softness.
- [x] 2.4 Add tests pinning the two added rules' presence in
      `_PLAN_SYSTEM_PROMPT`, and a test asserting the correct-refusal examples
      are still present.

## 3. Spec delta

- [x] 3.1 `specs/l3-spec-driven-planning/spec.md`: MODIFIED *Phase 1 — Planning
      Call* — add the two decline-precision bullets to the prompt's MUST
      instruct list.
- [x] 3.2 MODIFIED *Replan on Repeated Failure* — state that the replan prompt
      MUST NOT offer a refusal/error output shape, and that a replan response
      that is not a replacement subtask is a validation failure, not a decline.
- [x] 3.3 Scenarios: false-decline-capability, false-decline-transient-state,
      correct-refusal-preserved, correct-clarify-preserved, replan-returns-
      subtask-not-error.
- [x] 3.4 `openspec validate --strict` clean.

## 4. Hand back to the lead

- [ ] 4.1 Report the commit sha and the diff summary.
- [ ] 4.2 The lead runs the eval Job think-off; builder does not run cluster
      Jobs.
- [ ] 4.3 Report before/after per kind **from the Job log only**, against the
      11-14 baseline: exec 25/25, plan 19/25, replan 21/25.
- [ ] 4.4 If exec drops below 25/25, say so plainly and propose a revert rather
      than defending the change.
- [ ] 4.5 No image build until the lead asks.

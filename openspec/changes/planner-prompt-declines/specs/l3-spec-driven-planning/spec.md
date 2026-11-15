## MODIFIED Requirements

### Requirement: Phase 1 — Planning Call
L2 MUST call L3 once at task receipt with a planning prompt. The prompt MUST instruct L3 to:
- Decompose the task into ordered, atomic subtasks
- Define an explicit, observable completion criterion per subtask
- Prefer the machine-checkable criteria forms: "inventory has N item",
  "bot at (x, y, z)", "bot in dimension D", "killed N enemies",
  "block at (x,y,z) is B" — free-text criteria cannot be verified
- Cover EVERY action clause of the task (prepare AND travel AND fight ⇒
  all three appear as subtasks; trailing clauses MUST NOT be dropped)
- Treat non-primary dimensions (anything beyond overworld/nether/end) as
  special-purpose: do not stage work there unless the task names them
- Output ONLY valid JSON matching the plan schema (no prose, no fences)
- Keep each subtask small enough to map to 1–3 directives maximum
- Respect bot persona
- Distinguish a transient precondition from an impossibility: a state that does
  not hold *yet* (empty inventory, not in the required dimension, tool not held)
  MUST be planned around, not declined. Only world facts — a dimension the
  server does not have, an item that cannot be crafted or placed, a block that
  cannot be broken, two actions that cannot happen simultaneously — justify a
  `refuse`.
- Treat the bot's ability to speak to the player as available even though speech
  is not a plan directive kind. A task whose goal includes reporting an outcome
  MUST NOT be declined on the grounds that the directive list contains no chat
  directive.

#### Scenario: Planning call labeling
- GIVEN a bot initiating Phase 1
- WHEN the L3 call is made
- THEN the gateway client label is `aibot-agent:{bot_name}:PLAN`
- AND the log line at INFO is `[{bot_name}] L3 PLAN call — task: <truncated_text>`

#### Scenario: Transient state is planned around, not declined
- GIVEN a bot with an empty inventory
- WHEN the task is "put my things in the chest"
- THEN the returned JSON is a plan with subtasks
- AND it is NOT `{"kind":"refuse"}` and NOT `{"kind":"clarify"}`
- AND obtaining or carrying the items appears among the subtasks or their
  criteria

#### Scenario: Missing capability as a directive is not missing capability
- GIVEN the directive kind list contains no chat/message directive
- WHEN the task asks the bot to do work and report back when finished
- THEN the returned JSON is a plan with subtasks
- AND the response does not refuse on the grounds that no chat channel exists
- AND the reply `reason`, if any decline is returned, MUST NOT cite the absence
  of a chat directive

#### Scenario: Correct refusal of an impossible ask is preserved
- GIVEN a task naming a dimension the server does not generate
- WHEN L3 plans it
- THEN the response is `{"kind":"refuse","reason":...}`
- AND the reason names the missing world fact
- AND the plan does not substitute a nearby achievable goal

#### Scenario: Correct clarify of a vague ask is preserved
- GIVEN a task with no determinable subject or quantity ("go get some stuff")
- WHEN L3 plans it
- THEN the response is `{"kind":"clarify","reason":...}`
- AND the reason names the missing specificity

### Requirement: Replan on Repeated Failure

When a subtask has failed MAX_ATTEMPTS times, L2 MUST call L3 with a replan
prompt providing the failed subtask plus the accumulated error.

The replan prompt MUST require a single replacement subtask object and MUST NOT
offer a refusal or error output shape. A failed subtask is evidence that the
approach failed, not that the task is impossible; the model MUST revise the
approach rather than decline. If a model returns an error object anyway, L2
treats it as a validation failure, not as a decline.

A replan MAY change the subtask's description and approach but MUST NOT change
its completion criterion: L2 carries the original criterion through the splice
verbatim, with one evidence-gated exception — if the original criterion is
provably impossible (it targets a position outside the generated world) and the
replacement is not, the replacement MAY be accepted, and only an explicit
"keep original" escalation reply blocks it.

The spliced subtask replaces the failed subtask in place, preserving the
subtask `id`. The number of replans is tracked per subtask and bounded: once a
subtask has exhausted `MAX_REPLANS_PER_SUBTASK` replans, the plan is marked
`failed`.

#### Scenario: Replan splices new subtask
- GIVEN subtask 2 has failed and replans=0
- WHEN L2 calls L3 with the replan prompt
- THEN L3 returns a single replacement subtask object
- AND L2 validates it (schema valid, same id)
- AND L2 replaces subtask 2 in-place at the same `id`, restoring the ORIGINAL criteria string
- AND the replacement's replan count is the failed subtask's count plus one

#### Scenario: Replan attempts to weaken criteria
- GIVEN subtask 4 with criterion "killed 200 enemies" has failed
- WHEN L3's replacement subtask carries criterion "dispatched 200 hostile entities"
- THEN L2 keeps "killed 200 enemies" as the spliced subtask's criterion
- AND logs the rejected rewrite

#### Scenario: Replan refused
- GIVEN L3's replan response is invalid or fails schema validation
- WHEN L2 attempts to splice
- THEN the plan is marked `status = failed`

#### Scenario: Replan is not offered a refusal shape
- GIVEN the replan prompt text
- WHEN it is inspected
- THEN it does not present an error or refusal object as an allowed output
- AND it states the response must be a single replacement subtask object

#### Scenario: A refusal-shaped replan answer fails validation
- GIVEN a subtask has failed MAX_ATTEMPTS times
- WHEN L3 answers with `{"error": "<reason>"}` instead of a subtask
- THEN `PlanValidationError` is raised
- AND the plan is marked `status = failed` under the existing bounded-replan rule

#### Scenario: Replans are bounded
- GIVEN a subtask that has already been replanned MAX_REPLANS_PER_SUBTASK times
- WHEN the subtask fails again
- THEN L2 does NOT replan again
- AND the plan is marked `status = failed`

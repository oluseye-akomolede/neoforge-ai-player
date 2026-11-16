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

The prompt MUST also tell L3 that a task it cannot carry out is declined rather
than silently replaced by a different, doable-sounding one, and MUST give it the
two decline shapes — `clarify` for a task too vague to act on, `refuse` for one
that is impossible here or self-contradictory.

#### Scenario: Planning call labeling
- GIVEN a bot initiating Phase 1
- WHEN the L3 call is made
- THEN the gateway client label is `aibot-agent:{bot_name}:PLAN`
- AND the log line at INFO is `[{bot_name}] L3 PLAN call — task: <truncated_text>`

#### Scenario: Correct refusal of an impossible ask
- GIVEN a task naming a dimension the server does not generate
- WHEN L3 plans it
- THEN the response is `{"kind":"refuse","reason":...}`
- AND the reason names the missing world fact
- AND the plan does not substitute a nearby achievable goal

Rests on the shipped plan prompt's decline block (`ca27b6e`,
`agent/l3_planner.py::_PLAN_SYSTEM_PROMPT`):
- "If any part of the task names something this server does not have, or asks
  for two mutually exclusive things at once, you MUST decline — a plausible
  substitution is still a lie."
- `{{"kind": "refuse", "reason": "<one short why>"}}` … "Examples: * \"fly to
  the moon\" → refuse: there is no moon"
- "Do NOT convert these into a nearby achievable goal (e.g. \"go to the End\"
  for \"fly to the moon\"). Naming the real goal is the whole point."

#### Scenario: Correct clarify of a vague ask
- GIVEN a task with no determinable subject or quantity ("go get some stuff")
- WHEN L3 plans it
- THEN the response is `{"kind":"clarify","reason":...}`
- AND the reason names the missing specificity

Rests on the same block:
- `{{"kind": "clarify", "reason": "<one short question>"}}` "when the task is
  too vague to act on (\"go get some stuff\", \"make it better\") — ask what
  exactly is wanted, naming the ambiguity."
- "Examples: … * \"go get some stuff\" → clarify: which stuff, and how much."

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

Rests on the shipped replan prompt (`ca27b6e`,
`agent/l3_planner.py::_REPLAN_SYSTEM_PROMPT`):
- "Output ONLY a single replacement subtask JSON (no prose, no fences)"
- "You MUST return that one subtask object. There is no error form: a subtask
  that failed is a subtask to replace, not a reason to abandon the plan.
  Change the approach — different tool, different route, smaller first step,
  explicit prerequisites — until it can plausibly succeed."

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

## MODIFIED Requirements

### Requirement: Plan JSON Schema

Plan files MUST conform to this schema:

```json
{
  "task": "string — original task text",
  "bot": "string — bot name (forge, tiller, etc.)",
  "created_at": "ISO8601 timestamp",
  "status": "planning | executing | complete | failed",
  "subtasks": [
    {
      "id": "integer — 1-indexed",
      "description": "string — what this subtask accomplishes",
      "criteria": "string — explicit observable completion condition",
      "status": "pending | executing | complete | failed",
      "directives": ["array of directives emitted for this subtask"],
      "attempts": 0,
      "error": null
    }
  ],
  "current_subtask_id": 1,
  "meta": "object — free-form execution metadata (optional, defaults to {})"
}
```

`meta` carries values captured at plan creation that criteria evaluation needs
later. Known key: `kills_at_start` (int — the bot's lifetime `mob_kills` stat
when the plan was created; baseline for kill-count criteria).

`complete` and `failed` are terminal statuses.

#### Scenario: A written plan conforms to the schema
- GIVEN a bot that has just planned a task
- WHEN the plan file is read back
- THEN it carries `task`, `bot`, `created_at`, `status`, `subtasks`, and `current_subtask_id`
- AND each subtask carries `id`, `description`, `criteria`, `status`, `directives`, `attempts`, and `error`

#### Scenario: Kill baseline is captured at creation
- GIVEN a plan created for a bot with `mob_kills = 57`
- WHEN the plan file is written
- THEN `meta.kills_at_start` is 57

### Requirement: Phase 2 — Execution Call

For each pending subtask, L2 MUST call L3 with an execution prompt providing:
- The full plan (so L3 has whole-task context)
- ONLY the current subtask (focused execution)
- Current world-state summary (inventory, position, nearby entities, etc.)
- The previous error if this is a retry

L3's output for Phase 2 MUST be one or more directives in the existing directive
format.

#### Scenario: Execution prompt is scoped to the current subtask
- GIVEN a bot executing subtask 3 of 5
- WHEN Phase 2 is called
- THEN the prompt contains the full plan
- AND it contains only subtask 3 as the work to do
- AND it contains the current world-state summary

#### Scenario: Retry carries the previous error
- GIVEN a subtask retrying after a failed attempt
- WHEN Phase 2 is called for it
- THEN the prompt includes the previous attempt's error

#### Scenario: Execution returns directives in the existing format
- GIVEN a Phase 2 call for a pending subtask
- WHEN L3 responds
- THEN the response is one or more directives in the existing directive format

### Requirement: Bot Persona in Prompts

Phase 1 and Phase 2 prompts MUST include the bot's persona context:

- **Axiom** — generalist; plans flexibly across any task domain
- **Forge** — builder; plans in terms of materials, coordinates, construction sequences
- **Mystic** — mage; plans around enchantments, potions, magical resources
- **Scout** — explorer; plans in terms of movement, mapping, resource discovery
- **Tiller** — farmer; plans around crop cycles, soil, water, harvest sequences

A bot name with no matching persona MUST fall back to the generalist persona
rather than fail the call.

#### Scenario: Persona is included for a known bot
- GIVEN a planning call for a bot named Forge
- WHEN the prompt is built
- THEN it includes Forge's builder persona context

#### Scenario: Unknown bot name falls back to generalist
- GIVEN a planning call for a bot name not in the persona map
- WHEN the prompt is built
- THEN the generalist persona is used
- AND the call is not failed for lack of a persona

### Requirement: Criteria Evaluation Strategies

L2 MUST evaluate subtask completion criteria by trying these strategies in this
order, stopping at the first that returns a verdict:

1. **Deterministic world-state query** — if the criterion is structural (e.g.
   "block placed at X,Y,Z", "inventory has 16 wheat", "bot in dimension D"),
   L2 queries world state via the mod API directly. Compound criteria joined by
   AND/&& MUST be split and EVERY clause evaluated: any checkable clause failing
   fails the criterion; all clauses checkable and passing passes it; anything
   less abstains to the later strategies.
2. **Kill-stat delta** — if the criterion names a kill count, L2 compares the
   bot's current `mob_kills` stat against `plan.meta["kills_at_start"]`;
   satisfied iff `current − baseline ≥ target`. If no baseline was captured,
   the strategy MUST report not-satisfied with the lifetime count in the reason
   rather than defer to LLM judgment. If the mod does not expose the stat, the
   strategy abstains.
3. **L1 result check** — L1 directive returns a result with status / context;
   L2 checks the result string against the criterion heuristically.
4. **L3 evaluation fallback** — if none of (1)–(3) is conclusive, L2 calls L3
   with criterion + evidence and asks for a boolean.

If no strategy decides, the evaluation returns `inconclusive` and the subtask is
NOT treated as complete.

The evaluator returns, alongside the verdict, the name of the strategy that
decided it. The strategy names are `world_state`, `kill_stat`, `result_text`,
`l3_fallback`, and `inconclusive`.

#### Scenario: Inventory check (strategy 1)
- GIVEN a subtask with criterion "inventory has 16 wheat"
- WHEN L2 queries the mod API for the bot's inventory
- THEN if wheat count >= 16, the subtask is marked complete without an L3 call
- AND the deciding strategy is reported as `world_state`

#### Scenario: Position check (strategy 1)
- GIVEN a subtask with criterion "bot at (100, 64, -200)"
- WHEN L2 queries the bot's position
- THEN strategy 1 evaluates immediately

#### Scenario: Kill-count check (strategy 2)
- GIVEN a plan with `meta.kills_at_start = 57` and a subtask with criterion "killed 200 enemies"
- WHEN L2 queries the bot's kill stat and reads `mob_kills = 260`
- THEN the delta is 203 >= 200 and the subtask is marked complete without an L3 call
- AND the deciding strategy is reported as `kill_stat`

#### Scenario: Kill-count check without baseline
- GIVEN a plan whose `meta` lacks `kills_at_start` and a subtask with criterion "killed 200 enemies"
- WHEN L2 queries the kill stat
- THEN the strategy returns NOT satisfied with the lifetime count in the reason
- AND does NOT fall through to L3 judgment

#### Scenario: Kill strategy runs before result-text
- GIVEN a subtask whose criterion names a kill count AND whose last L1 result text also contains a matching number
- WHEN L2 evaluates the criterion
- THEN the kill-stat strategy decides, not the result-text heuristic
- AND the deciding strategy is `kill_stat`

#### Scenario: No strategy decides
- GIVEN a subtask whose criterion no strategy can resolve and no model is available
- WHEN L2 evaluates the criterion
- THEN the result is NOT satisfied
- AND the deciding strategy is reported as `inconclusive`

#### Scenario: L3 fallback (strategy 4)
- GIVEN a subtask with criterion "the structure looks well-built"
- WHEN no earlier strategy can decide
- THEN L2 calls L3 with `{criterion, evidence, world_state_summary}`
- AND L3 returns `{satisfied: bool, reason: str}`
- AND the deciding strategy is `l3_fallback`

### Requirement: Replan on Repeated Failure

When a subtask has failed MAX_ATTEMPTS times, L2 MUST call L3 with a replan
prompt providing the failed subtask plus the accumulated error.

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

#### Scenario: Replans are bounded
- GIVEN a subtask that has already been replanned MAX_REPLANS_PER_SUBTASK times
- WHEN the subtask fails again
- THEN L2 does NOT replan again
- AND the plan is marked `status = failed`

## ADDED Requirements

### Requirement: Plan-Aware Planning Entry Points

The plan layer's Phase 1 and Phase 2 calls MUST be exposed as
`plan_task()` and `execute_subtask()` (agent-side), and the L3 client must
expose the matching calls for planning, per-subtask execution, and replanning.

The legacy single-shot `decompose()` and `orchestrate()` entry points MUST NOT
be the plan-aware path: they remain in their original modules
(`agent/planner.py`, `agent/openai_brain.py`) and are not rewritten to call
`plan_task()`. Any code that still calls them is on the pre-plan path.

#### Scenario: Plan layer drives through plan_task/execute_subtask
- GIVEN a bot receiving a task with the L3 plan layer enabled
- WHEN the task is planned and executed
- THEN the planning call is `plan_task` and each subtask call is `execute_subtask`
- AND the single-shot `decompose`/`orchestrate` path is not used

#### Scenario: Legacy entry points are not the plan layer
- GIVEN the pre-plan single-shot path
- WHEN it is invoked
- THEN it does not read or write a plan file
- AND it does not go through `plan_task`/`execute_subtask`

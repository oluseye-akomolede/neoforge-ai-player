# L3 Spec-Driven Planning Specification

## Purpose
Defines how the agent (L2) drives the LLM (L3) to plan and then execute bot tasks one subtask at a time, with a persisted plan file as the single source of truth. Splits LLM work into a one-time Phase 1 (planning) and a repeating Phase 2 (per-subtask execution). Applies to all bots: Axiom, Forge, Mystic, Scout, Tiller.

## Requirements

### Requirement: Stateless L3, L2 Owns Plan State
L3 (Ollama LLM via llm-gateway) MUST be stateless. L2 (the agent process per bot) MUST own all plan state. Plan progress is read from / written to the plan file before and after every state transition.

#### Scenario: L3 never tracks its own progress
- GIVEN a bot executing subtask 2 of 5
- WHEN L3 is called for Phase 2 (execution)
- THEN the prompt provides the full plan + the current subtask explicitly
- AND L3 is never asked to "decide which subtask is next" or "track which is done"

### Requirement: Plan File Location and Lifecycle
Each bot MUST have at most one active plan file at:
`agent_plans/{bot_name}_current.json`

Examples:
- `agent_plans/forge_current.json`
- `agent_plans/tiller_current.json`
- `agent_plans/scout_current.json`

#### Scenario: Plan written on Phase 1 completion
- GIVEN a bot receives a new task
- WHEN Phase 1 generates a valid plan
- THEN the plan is written to disk before any Phase 2 call
- AND any prior `_current.json` for that bot is overwritten

#### Scenario: Plan archived on completion
- GIVEN a bot's plan reaches `status = complete`
- WHEN the final subtask criterion is met
- THEN the file is moved to `agent_plans/archive/{bot_name}_{timestamp}.json`
- AND no `_current` file exists for that bot

#### Scenario: Plan archived on abandonment
- GIVEN a bot's plan is marked failed
- WHEN cleanup runs
- THEN the file is moved to `agent_plans/archive/{bot_name}_{timestamp}.json` with `status = failed`

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
  "current_subtask_id": 1
}
```

### Requirement: Phase 1 — Planning Call
L2 MUST call L3 once at task receipt with a planning prompt. The prompt MUST instruct L3 to:
- Decompose the task into ordered, atomic subtasks
- Define an explicit, observable completion criterion per subtask
- Output ONLY valid JSON matching the plan schema (no prose, no fences)
- Keep each subtask small enough to map to 1–3 directives maximum
- Respect bot persona

#### Scenario: Planning call labeling
- GIVEN a bot initiating Phase 1
- WHEN the L3 call is made
- THEN the gateway client label is `aibot-agent:{bot_name}:PLAN`
- AND the log line at INFO is `[{bot_name}] L3 PLAN call — task: <truncated_text>`

### Requirement: Phase 2 — Execution Call
For each pending subtask, L2 MUST call L3 with an execution prompt providing:
- The full plan (so L3 has whole-task context)
- ONLY the current subtask (focused execution)
- Current world-state summary (inventory, position, nearby entities, etc.)
- The previous error if this is a retry

L3's output for Phase 2 MUST be one or more directives in the existing directive format.

#### Scenario: Execution call labeling
- GIVEN a bot executing subtask N of M
- WHEN the L3 call is made
- THEN the gateway client label is `aibot-agent:{bot_name}:EXEC`
- AND the log line at INFO is `[{bot_name}] L3 EXEC call — subtask N/M`

### Requirement: Subtask Lifecycle State Machine
L2 MUST drive subtasks through this state machine:

```
pending → executing → (complete | failed)
failed (attempts < MAX_ATTEMPTS) → pending (retry)
failed (attempts >= MAX_ATTEMPTS) → triggers replan
```

`MAX_ATTEMPTS` defaults to 3.

#### Scenario: Successful subtask flow
- GIVEN subtask 2 status=pending
- WHEN Phase 2 runs and L1 reports completion meeting the criterion
- THEN subtask 2 transitions pending → executing → complete
- AND `current_subtask_id` advances to 3
- AND the plan file is rewritten

#### Scenario: Retry on failure
- GIVEN subtask 2 status=pending, attempts=0
- WHEN L1 reports failure
- THEN subtask 2 transitions pending → executing → failed
- AND attempts increments to 1
- AND if attempts < MAX_ATTEMPTS, status flips back to pending for retry

### Requirement: Replan on Repeated Failure
When a subtask has failed MAX_ATTEMPTS times, L2 MUST call L3 with a replan prompt providing the failed subtask + accumulated error.

#### Scenario: Replan splices new subtask
- GIVEN subtask 2 has attempts=3 and is failed
- WHEN L2 calls L3 with the replan prompt
- THEN L3 returns a single replacement subtask object
- AND L2 validates it (schema valid, same id, status=pending)
- AND L2 replaces subtask 2 in-place
- AND attempts is reset to 0

#### Scenario: Replan refused
- GIVEN L3's replan response is invalid or L3 returns `{"error": "..."}`
- WHEN L2 attempts to splice
- THEN the plan is marked `status = failed`

### Requirement: Criteria Evaluation Strategies
L2 MUST evaluate subtask completion criteria using these strategies, in this order:

1. **Deterministic world-state query** — if the criterion is structural (e.g. "block placed at X,Y,Z", "inventory has 16 wheat"), L2 queries world state via the mod API directly
2. **L1 result check** — L1 directive returns a result with status / context; L2 checks the result against the criterion string heuristically
3. **L3 evaluation fallback** — if neither (1) nor (2) is conclusive, L2 calls L3 with criterion + evidence and asks for a boolean

#### Scenario: Inventory check (strategy 1)
- GIVEN a subtask with criterion "inventory has 16 wheat"
- WHEN L2 queries the mod API for the bot's inventory
- THEN if wheat count >= 16, the subtask is marked complete without an L3 call

#### Scenario: Position check (strategy 1)
- GIVEN a subtask with criterion "bot at (100, 64, -200)"
- WHEN L2 queries the bot's position
- THEN strategy 1 evaluates immediately

#### Scenario: L3 fallback (strategy 3)
- GIVEN a subtask with criterion "the structure looks well-built"
- WHEN neither strategy 1 nor 2 can decide
- THEN L2 calls L3 with `{criterion, evidence, world_state_summary}` at priority=4
- AND L3 returns `{satisfied: bool, reason: str}`

### Requirement: Bot Persona in Prompts
Phase 1 and Phase 2 prompts MUST include the bot's persona context:

- **Axiom** — generalist; plans flexibly across any task domain
- **Forge** — builder; plans in terms of materials, coordinates, construction sequences
- **Mystic** — mage; plans around enchantments, potions, magical resources
- **Scout** — explorer; plans in terms of movement, mapping, resource discovery
- **Tiller** — farmer; plans around crop cycles, soil, water, harvest sequences

### Requirement: ollama_lock / Gateway Compatibility
The two-phase pattern adds one extra LLM call per task (planning) + extra per-subtask calls. The existing global `ollama_lock` (or its replacement, llm-gateway priority queue) already serializes GPU access. No lock changes are required.

#### Scenario: Concurrent bots share gateway
- GIVEN Forge and Tiller both have active plans
- WHEN both make Phase 2 calls simultaneously
- THEN llm-gateway queues them at priority=3 (specialist L3 lane)
- AND they are serialized through MAX_INFLIGHT

### Requirement: Dashboard Visibility
Plan files MUST be servable to the React dashboard via the agent's HTTP API:

| Method | Path | Returns |
|---|---|---|
| GET | /api/plans | List of all active plans (`_current.json` files) — `[{bot, status, subtask_count, current_subtask_id, current_subtask_desc, current_attempts}]` |
| GET | /api/plans/{bot} | Full plan JSON for a specific bot |
| GET | /api/plans/archive | Recent archived plans (default 50) |

#### Scenario: Dashboard surfaces active plans
- GIVEN three bots with active plans
- WHEN the dashboard polls `/api/plans`
- THEN it receives a 3-row summary suitable for a list/progress view

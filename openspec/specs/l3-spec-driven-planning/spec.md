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
  "current_subtask_id": 1,
  "meta": "object — free-form execution metadata (optional, defaults to {})"
}
```

`meta` carries values captured at plan creation that criteria evaluation
needs later. Known keys: `kills_at_start` (int — the bot's lifetime
`mob_kills` stat when the plan was created; baseline for kill-count
criteria).

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

### Requirement: Directive Normalization
Before dispatching a Phase 2 directive, L2 MUST normalize it (translation
only — no judgment):
- Uppercase `kind` and resolve known aliases: `EQUIP` → `EQUIP_ALL`
  (there is no per-item equip directive; the mod exposes bulk equip only)
- Canonicalize COMBAT targets through the mob-synonym table (e.g.
  `minecraft:pig_zombie` / `zombie_pigman` → `minecraft:zombified_piglin`,
  `wither_boss` → `wither`, `snowman` → `snow_golem`,
  `villager_golem` → `iron_golem`)
- A `kind` outside the known vocabulary MUST be surfaced to the retry
  prompt as `unknown_kind:<KIND>` so L3 can correct it, rather than
  failing silently

#### Scenario: Invented EQUIP directive
- GIVEN L3 emits `{"kind": "EQUIP", "target": "armor_set"}`
- WHEN L2 normalizes the directive
- THEN it dispatches as `EQUIP_ALL` via the mod's bulk-equip endpoint
- AND the subtask does not burn an attempt on an unknown kind

#### Scenario: Renamed mob id
- GIVEN L3 emits `{"kind": "COMBAT", "target": "minecraft:pig_zombie"}`
- WHEN L2 normalizes the directive
- THEN the target is rewritten to `minecraft:zombified_piglin`

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

A replan MAY change the subtask's description and approach but MUST NOT
change its completion criterion: L2 carries the original criterion through
the splice verbatim. (War-test round 2: L3 reworded failed kill criteria
into verifier-dodging synonyms and every plan finalized "complete" at 0
kills.)

#### Scenario: Replan splices new subtask
- GIVEN subtask 2 has attempts=3 and is failed
- WHEN L2 calls L3 with the replan prompt
- THEN L3 returns a single replacement subtask object
- AND L2 validates it (schema valid, same id, status=pending)
- AND L2 replaces subtask 2 in-place, restoring the ORIGINAL criteria string
- AND attempts is reset to 0

#### Scenario: Replan attempts to weaken criteria
- GIVEN subtask 4 with criterion "killed 200 enemies" has failed 3 attempts
- WHEN L3's replacement subtask carries criterion "dispatched 200 hostile entities"
- THEN L2 keeps "killed 200 enemies" as the spliced subtask's criterion
- AND logs the rejected rewrite

#### Scenario: Replan refused
- GIVEN L3's replan response is invalid or L3 returns `{"error": "..."}`
- WHEN L2 attempts to splice
- THEN the plan is marked `status = failed`

### Requirement: Criteria Evaluation Strategies
L2 MUST evaluate subtask completion criteria using these strategies, in this order:

1. **Deterministic world-state query** — if the criterion is structural (e.g. "block placed at X,Y,Z", "inventory has 16 wheat", "bot in dimension D"), L2 queries world state via the mod API directly (`/bot/{name}/inventory`, `/bot/{name}/status`, `/bot/{name}/block_at`). Compound criteria joined by AND/&& MUST be split and EVERY clause evaluated: any checkable clause failing fails the criterion; all clauses checkable and passing passes it; anything less abstains to the later strategies. (War-game finding 13/14: wrong endpoint paths meant this strategy never ran, and compound criteria were judged by their first clause via result-text tokens — two bots "completed" fortresses that did not exist.)
2. **Kill-stat delta** — if the criterion names a kill count (e.g. "killed 200 enemies", "slay 200", "200 kills"), L2 compares the bot's current `mob_kills` stat against `plan.meta["kills_at_start"]`; satisfied iff `current − baseline ≥ target`. If no baseline was captured, the strategy MUST fail conservatively (reporting the lifetime count) rather than defer to LLM judgment. If the mod does not expose the stat, the strategy abstains.
3. **L1 result check** — L1 directive returns a result with status / context; L2 checks the result against the criterion string heuristically
4. **L3 evaluation fallback** — if none of (1)–(3) is conclusive, L2 calls L3 with criterion + evidence and asks for a boolean

#### Scenario: Inventory check (strategy 1)
- GIVEN a subtask with criterion "inventory has 16 wheat"
- WHEN L2 queries the mod API for the bot's inventory
- THEN if wheat count >= 16, the subtask is marked complete without an L3 call

#### Scenario: Position check (strategy 1)
- GIVEN a subtask with criterion "bot at (100, 64, -200)"
- WHEN L2 queries the bot's position
- THEN strategy 1 evaluates immediately

#### Scenario: Kill-count check (strategy 2)
- GIVEN a plan with `meta.kills_at_start = 57` and a subtask with criterion "killed 200 enemies"
- WHEN L2 queries `/bot status` and reads `mob_kills = 260`
- THEN the delta is 203 ≥ 200 and the subtask is marked complete without an L3 call

#### Scenario: Kill-count check without baseline
- GIVEN a plan whose `meta` lacks `kills_at_start` and a subtask with criterion "killed 200 enemies"
- WHEN L2 queries the kill stat
- THEN the strategy returns NOT satisfied with the lifetime count in the reason
- AND does NOT fall through to L3 judgment

#### Scenario: L3 fallback (strategy 4)
- GIVEN a subtask with criterion "the structure looks well-built"
- WHEN no earlier strategy can decide
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

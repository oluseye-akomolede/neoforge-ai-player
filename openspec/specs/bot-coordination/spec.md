# Bot Coordination Specification

## Purpose
Defines how multiple bots coordinate work — orchestration, task board, specialization matching, and the four-tier AI planning pipeline.

## Requirements

### Requirement: Single Coordinator
When a player sends a multi-bot instruction, exactly one bot MUST act as coordinator. Other bots wait for task board assignments.

#### Scenario: Orchestrated multi-bot task
- GIVEN a player says "all bots mine 100 iron_ore"
- WHEN the first bot receives the message
- THEN it becomes coordinator, decomposes the task, and posts sub-tasks to the task board
- AND other bots claim their assigned tasks from the board

### Requirement: Task Board
The system MUST maintain a PostgreSQL-backed task board with atomic claiming via `FOR UPDATE SKIP LOCKED`.

#### Scenario: Concurrent task claiming
- GIVEN two idle bots check the task board simultaneously
- WHEN both try to claim the same task
- THEN exactly one succeeds; the other sees the next available task

### Requirement: Task Lifecycle
Tasks MUST follow the status flow: pending → assigned → in_progress → done | failed.

#### Scenario: Task progresses through lifecycle
- GIVEN a task is posted to the task board with status pending
- WHEN a bot claims the task
- THEN the status MUST change to assigned
- AND when the bot begins execution the status changes to in_progress
- AND when the bot finishes the status changes to done or failed

### Requirement: Task Structure
Each task MUST contain:

| Field | Type | Description |
|-------|------|-------------|
| id | int | Auto-increment identifier |
| description | string | Human-readable task description |
| assigned_to | string | Bot name (null if unassigned) |
| status | enum | pending, assigned, in_progress, done, failed |
| specializations | string[] | Required specializations for matching |
| plan_steps | json | Pre-planned L1 directive steps (optional) |
| created_at | timestamp | Creation time |
| claimed_at | timestamp | When claimed by a bot |

#### Scenario: Task contains all required fields
- GIVEN a coordinator decomposes a player instruction into sub-tasks
- WHEN a task is inserted into the task board
- THEN it MUST contain an id, description, status, specializations, and created_at at minimum
- AND assigned_to and claimed_at are null until a bot claims it

### Requirement: Specialization Matching
Task claiming MUST prefer bots whose specializations match the task's required specializations:

| Bot | Specializations |
|-----|----------------|
| Axiom | crafting, mining, general |
| Forge | building, crafting |
| Mystic | magic, enchanting, brewing |
| Scout | gathering, mining, combat |
| Tiller | farming, gathering, crafting |

#### Scenario: Specialized bot is preferred for matching task
- GIVEN a task requiring the mining specialization is posted to the task board
- WHEN both Axiom (crafting, mining, general) and Forge (building, crafting) are idle
- THEN Axiom MUST be preferred because its specializations include mining
- AND Forge is skipped for this task

### Requirement: Stale Task Release
Tasks stuck in in_progress for more than 300 seconds MUST be automatically released back to pending.

#### Scenario: Stale task is released after timeout
- GIVEN a task has been in in_progress status for more than 300 seconds
- WHEN the stale task reaper runs
- THEN the task status MUST be reset to pending
- AND assigned_to MUST be cleared so another bot can claim it

### Requirement: Task Completion Reward
Bots MUST receive 5 XP levels upon completing a task board task.

#### Scenario: Bot receives XP on task completion
- GIVEN a bot has claimed and is executing a task board task
- WHEN the bot completes the task successfully with status done
- THEN the bot MUST receive 5 XP levels as a reward

### Requirement: Four-Tier AI Pipeline
The planning pipeline MUST escalate through four tiers:

| Tier | Location | Latency | Description |
|------|----------|---------|-------------|
| L1 | Mod (Java) | ~0ms | Directive → Behavior state machine |
| L2 | Agent (Python) | ~100ms | Parameter adjustment on L1 failure |
| L3 | Ollama | 2-10s | LLM planning via qwen2.5:14b-instruct |
| L4 | OpenAI | 1-3s | Cloud escalation via gpt-4o-mini (optional) |

#### Scenario: L1 failure escalates to L2
- GIVEN a MINE directive for oak_log fails (not found)
- WHEN L2 receives the failure
- THEN it tries alternative names (birch_log, spruce_log) and expands radius

### Requirement: L3 WIDE_SEARCH Awareness
The L3 planner and orchestrator MUST recognize search instructions and generate WIDE_SEARCH steps. The step classifier (`_classify_step`) MUST parse "Wide search for X" into a WIDE_SEARCH directive. The planner prompt MUST include wide_search as a known action pattern.

#### Scenario: Single-bot search via L3
- GIVEN a player says "Scout search for diamond_ore"
- WHEN the planner decomposes the instruction
- THEN it produces a step "Wide search for diamond_ore"
- AND `_classify_step` maps it to a WIDE_SEARCH directive with search_type=block

### Requirement: Coordinated Search Grid Injection
When the orchestrator distributes WIDE_SEARCH steps to multiple bots, it MUST inject grid-slicing metadata into each step's text as `[grid N/M]` (where N is bot_index, M is total bot_count). The step classifier MUST parse this notation and pass bot_index/bot_count in the directive's extra params.

#### Scenario: All-bots search with grid slicing
- GIVEN a player says "all bots search for ancient_debris" and 5 bots are available
- WHEN the orchestrator redistributes the step to all bots
- THEN each bot receives a step like "Wide search for ancient_debris [grid 0/5]" through "[grid 4/5]"
- AND `_classify_step` extracts bot_index and bot_count from the grid notation
- AND the resulting WIDE_SEARCH directives have extra.bot_index=0..4 and extra.bot_count=5

### Requirement: Directive Loss Detection
When polling for directive status, the agent MUST distinguish between "directive completed" and "directive lost to server restart" by tracking recent connection errors within a 30-second window.

#### Scenario: Agent detects directive lost to restart
- GIVEN the agent has sent a directive to the mod and is polling for status
- WHEN the mod returns no active directive and a connection error occurred within the last 30 seconds
- THEN the agent MUST classify the directive as lost rather than completed
- AND the agent MUST re-issue or escalate the directive

### Requirement: Fleet-Wide Orders

An order MAY be addressed to the whole fleet. A fleet order MUST be delivered to
every living fleet bot, and each bot MUST run its own independent plan for its
assignment — a failure on one bot MUST NOT abort the others.

A fleet order MAY be typed or free text (TEXT). A typed fleet order fans out
verbatim to every bot. A TEXT fleet order MUST first be partitioned: one L3 call
receives the fleet's per-bot personas and holdings summaries and returns one
short assignment per bot, where a bot MAY be assigned "skip". If the partition
call fails or its reply cannot be parsed, the order MUST fall back to verbatim
fan-out rather than being dropped.

Fleet orders carry a shared fleet id on the order wire so the dashboard can
render them as one umbrella with per-bot status.

#### Scenario: Typed fleet order fans out verbatim
- GIVEN several bots are online
- WHEN a typed fleet order is submitted to the fleet address
- THEN one order entry per living bot is created
- AND each bot runs the same order verbatim
- AND all entries carry a shared fleet id

#### Scenario: Text fleet order is partitioned per bot
- GIVEN a free-text fleet order and the fleet's personas and holdings
- WHEN the order is submitted
- THEN one L3 partition call assigns each bot a short instruction
- AND a bot whose assignment is "skip" is given no order
- AND the remaining bots each run their own plan

#### Scenario: Partition failure degrades to verbatim fan-out
- GIVEN the partition call errors or returns an unparsable reply
- WHEN the fleet order is submitted
- THEN every bot receives the original order text verbatim
- AND the order is not dropped

#### Scenario: One bot's failure does not abort siblings
- GIVEN a fleet order running across several bots
- WHEN one bot's plan fails
- THEN the other bots continue to completion
- AND the umbrella row shows per-bot status

### Requirement: Standing Orders

A standing order is a persistent watcher: a condition over observable state, an
action to fire when the condition is broken, and a recorded result. Standing
orders MUST be owned by the mod as definitions and by the agent as judgement.

The agent MUST evaluate standing orders on a periodic cadence. An action MUST
fire only when the condition is broken, the bot is idle, and the order's
cooldown has lapsed. A fired action MUST enter the same order lane as any other
order, so all downstream triggers still apply.

Repeatedly failing orders MUST back off exponentially and raise ONE inbox item
rather than firing continuously. A per-bot cap on standing orders MUST be
enforced with an honest refusal beyond the cap.

Watch types are `me_count`, `vault_count`, and `xp_level`.

#### Scenario: A broken condition fires the action once
- GIVEN a standing order "keep >= 32 quartz dust" with the network below 32
- WHEN the watcher evaluates the order on its cadence and the bot is idle
- THEN exactly one action is dispatched through the normal order lane
- AND the order records the fire and result

#### Scenario: An unbroken condition does not fire
- GIVEN a standing order whose condition currently holds
- WHEN the watcher evaluates the order
- THEN no action is dispatched

#### Scenario: Failure backs off instead of nagging
- GIVEN a standing order whose action keeps failing
- WHEN it fails repeatedly
- THEN the interval between attempts grows
- AND exactly one inbox item is raised, not one per failure

#### Scenario: Per-bot cap refuses honestly
- GIVEN a bot already at its standing-order cap
- WHEN another standing order is created for it
- THEN the creation is refused with a reason

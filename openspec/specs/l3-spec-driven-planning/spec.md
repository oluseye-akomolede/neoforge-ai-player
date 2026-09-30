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

A plan MUST be written to disk before any Phase 2 call, and any prior
`_current.json` for that bot MUST be overwritten. A plan reaching a terminal
state MUST be archived to `agent_plans/archive/{bot_name}_{timestamp}.json`,
after which no `_current` file exists for that bot. The terminal states are
`complete`, `failed`, and `cancelled`. A plan that never executed because the
planning step declined MUST still be written and archived, so the decline is
visible rather than vanishing.

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
- GIVEN a bot's plan is marked failed or cancelled
- WHEN cleanup runs
- THEN the file is moved to `agent_plans/archive/{bot_name}_{timestamp}.json` with `status = failed` or `status = cancelled`

#### Scenario: Declined plan is archived
- GIVEN a planning step that declined
- WHEN the plan is finalized
- THEN a failed plan carrying the decline is written and archived
- AND no subtask was ever dispatched

### Requirement: Plan JSON Schema

Plan files MUST conform to this schema:

```json
{
  "task": "string — original task text",
  "bot": "string — bot name (forge, tiller, etc.)",
  "created_at": "ISO8601 timestamp",
  "status": "planning | executing | complete | failed | cancelled",
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

`complete`, `failed`, and `cancelled` are terminal statuses. `cancelled` is
distinct from `complete`: a cancelled plan stopped short of its subtasks.

`meta` MAY additionally carry:

| key | type | meaning |
|---|---|---|
| `declined` | `clarify` \| `refuse` | the planning step declined instead of planning |
| `reason` | string | the short reason the bot spoke to the player |
| `unfinished_subtasks` | string | ids of subtasks not `complete` when the plan was failed at finalize |

#### Scenario: A written plan conforms to the schema

- **GIVEN** a bot that has just planned a task
- **WHEN** the plan file is read back
- **THEN** it carries `task`, `bot`, `created_at`, `status`, `subtasks`, and `current_subtask_id`
- **AND** each subtask carries `id`, `description`, `criteria`, `status`, `directives`, `attempts`, and `error`

#### Scenario: Kill baseline is captured at creation

- **GIVEN** a plan created for a bot with `mob_kills = 57`
- **WHEN** the plan file is written
- **THEN** `meta.kills_at_start` is 57

#### Scenario: Cancelled plan is valid and terminal

- **GIVEN** a plan cancelled by a stop
- **WHEN** the plan file is read back
- **THEN** its status is `cancelled`
- **AND** it is treated as terminal, not as an incomplete execution

#### Scenario: Declined plan preserves its reason

- **GIVEN** a plan whose planning step returned `refuse`
- **WHEN** the plan file is read back
- **THEN** its status is `failed`
- **AND** its metadata carries the decline kind and the reason the bot spoke

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

### Requirement: Chat Is Answered, Not Planned

A player chat message addressed to a bot MUST first be classified as conversation
or order. A conversational message SHALL be answered in the bot's persona and
sent to server chat, and MUST NOT start a plan.

Classification MUST default to `task` on any error, timeout, or unrecognised
reply, so an order is never silently dropped.

#### Scenario: Character question is answered without a plan

- **WHEN** a player says "Mystic, who are you?"
- **THEN** the bot replies in server chat in its persona
- **AND** no plan file is written and no subtask is dispatched
- **AND** the agent log shows the message was handled on the conversation path

#### Scenario: A message that opens with a greeting is not discarded

- **WHEN** a player says "Hi Mystic! Who are you?"
- **THEN** the message is classified and answered on the conversation path
- **AND** it is not dropped merely because it begins with a greeting
- **AND** a message that is *only* a greeting or acknowledgement may be ignored,
  and any ignored message is logged so the drop is visible

#### Scenario: An instruction still plans

- **WHEN** a player says "Scout, gather 4 oak logs"
- **THEN** the message is classified as a task
- **AND** the plan layer runs exactly as it did before this change

#### Scenario: Classifier failure does not swallow an order

- **GIVEN** the classifier call errors or returns an unrecognised kind
- **WHEN** a player addresses the bot
- **THEN** the message is treated as a task
- **AND** the bot does not answer with a conversational reply instead of acting

### Requirement: Stop Cancels a Running Plan

A stop signal SHALL abort the bot's running plan. The plan MUST be finalized
`cancelled` — never `complete` — and the bot SHALL confirm in chat.

The abort is delivered by a per-run cancellation signal that the plan layer
checks between subtasks, before each subtask attempt, after the per-subtask
planning call returns, and before each directive is dispatched. Checking only at
the attempt boundary is not sufficient: a stop that lands while a long L3 call or
an earlier directive is in flight is set after that check, and any directive the
attempt produces would otherwise still be sent. Clearing plan state on the
agent's main thread is not sufficient on its own, because the plan runs on a
separate thread.

#### Scenario: Stop during a running plan

- **GIVEN** a bot is executing a multi-subtask plan
- **WHEN** a player says "stop"
- **THEN** the orchestrator aborts before dispatching the next subtask
- **AND** the plan is finalized `cancelled`
- **AND** the bot says "Stopping." in chat
- **AND** the plan is not reported `complete`

#### Scenario: Stop during a subtask's planning call is not overtaken by its directives

- **GIVEN** a bot is executing a subtask and its plan-time L3 call is in flight
- **WHEN** a player says "stop" before that call returns
- **THEN** none of the directives the call returns are dispatched
- **AND** the plan is finalized `cancelled`, not `complete`

#### Scenario: Stop does not lose a signal that arrives before the plan thread is listening

- **GIVEN** a stop or reset arrives in the window after the plan thread is
  started but before it publishes its cancellation signal
- **WHEN** the plan thread publishes the signal
- **THEN** it observes the stop and does not dispatch a subtask

#### Scenario: Reset cancels a running plan

- **GIVEN** a bot is executing a plan
- **WHEN** the bot's state is reset
- **THEN** the running plan is cancelled by the same signal as a stop

#### Scenario: Stop with no plan running is harmless

- **GIVEN** a bot has no plan executing
- **WHEN** a player says "stop"
- **THEN** the bot acknowledges and no plan is created or finalized

### Requirement: Clarify or Refuse Instead of Inventing

The planning step MAY return a clarification or refusal instead of a plan. When it
does, the bot SHALL say the reason in server chat and MUST NOT dispatch any
subtask, and the plan SHALL be recorded as failed with the decline preserved.

The planning prompt MUST state that declining is required rather than substituting
a different, doable-sounding task; a plausible substitution is not an acceptable
plan.

#### Scenario: Vague request is questioned

- **WHEN** a player says "Tiller, go get some stuff"
- **THEN** the bot asks what and how much, in chat
- **AND** no subtask is executed
- **AND** the plan is failed, carrying the decline kind `clarify` and the reason

#### Scenario: Impossible request is refused

- **WHEN** a player asks for something the world does not permit
- **THEN** the bot declines in chat with a short reason
- **AND** no subtask is executed
- **AND** the decline kind `refuse` is preserved on the plan record

#### Scenario: Declining does not require a substituted plan

- **GIVEN** the planning call can answer with a clarify or refuse object
- **WHEN** it does
- **THEN** the plan layer accepts that answer without validation against the plan
  schema, because it is not a plan

### Requirement: Plan Complete Only If Every Subtask Passed

A plan SHALL be reported `complete` only if every subtask is `complete` at
finalize. Any subtask not `complete` MUST force the plan to `failed` and MUST be
recorded on the plan record.

The plan status MUST NOT be derived solely from how the execution loop exited,
because the loop also leaves "complete" when it runs off the end past abandoned
subtasks.

#### Scenario: Failed subtask cannot yield a complete plan

- **GIVEN** a plan whose loop exits with a subtask still failed
- **WHEN** the plan is finalized
- **THEN** the plan status is `failed`
- **AND** the unfinished subtask ids are recorded on the plan record

#### Scenario: Genuine completion is unaffected

- **GIVEN** a plan whose every subtask is `complete`
- **WHEN** the plan is finalized
- **THEN** the plan status is `complete`
- **AND** no unfinished-subtask marker is recorded

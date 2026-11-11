# AI Player: architecture facts for the blog post of Wed 11-18

Source of truth: the public AI Player repo at commit 6d0c04f (prepared locally; not pushed when
this file was written, so add the GitHub link only once it exists). Every `file:line` below refers to that commit. Paths are relative to the repo root.
`M/` is short for `src/main/java/com/oluseyeakomolede/aiplayermod/`.

The writer drafts from this file only. If a claim is not here, don't make it.

---

## 1. What it is

- AI Player is a Minecraft mod plus a Python agent that puts AI-controlled players onto a
  NeoForge 1.21.1 server. Each bot is a real server-side player entity, not a mob and not a
  network client (`M/bot/BotServerPlayer.java:10`, `class BotServerPlayer extends ServerPlayer`).
- The people on the server give the bots orders in plain English through in-game chat, for example
  "mine 20 iron and smelt it". The bots plan the job and carry it out in the world alongside them.
- Language models do the thinking at the top: they break orders into steps and handle the unusual
  cases. Ordinary Java code does the moment-to-moment playing, inside the server's own game tick.
- What it's for: a modded survival server where a player can hand off long, tedious jobs (mining,
  smelting, crafting, searching, storing, fighting) to a crew of helpers, keep giving orders in chat,
  and see what the crew is doing on a web dashboard.

## 2. What it's good at

There are no performance benchmarks in the repo. Every number below is a **configured limit or a
count of code**, not a measured speed or success rate. Say "is designed to" or "is capped at",
never "achieves".

| Claim | Kind | Evidence |
|---|---|---|
| The model and the game run at different speeds. The bot plays every server tick, while the agent loop checks in every 2 seconds by default. | default setting | `agent/config.py:89` (`TICK_DELAY` = 2.0); brain ticked from `M/bot/BotPlayer.java:502` |
| A wide action set: 37 directive types, from MINE, CRAFT, SMELT and COMBAT to container storage, vehicles and teleport | count of an enum | `M/brain/DirectiveType.java:3` (37 values) |
| Learned skills are bounded, so a bad one can't run forever: loops need `max_iterations`, at most 32 nested skill calls, at most 500 actions per skill run, and the validator refuses trees deeper than 64 | hard limits | `M/brain/behavior/SkillBehavior.java:38-39, 221`; `M/brain/skill/SkillValidator.java:50, 74` |
| The skill library can't grow without limit: 64 skills, least-recently-used evicted first, and the hand-written seed skills are never evicted | hard limit | `M/brain/skill/SkillRegistry.java:23, 37, 95-105` |
| A skill can be checked against the world: an optional `verify` rule turns "finished" into "failed" if the inventory doesn't show the result | design | `M/brain/skill/SkillSpec.java` (header comment, `verify`) |
| Whether a step is done is decided from the world, not from the model's own word: world-state queries come first, then the last action's result, and only then a yes/no model judgment | design | `agent/criteria_eval.py:1-9` |
| When the player is away, the bots carry on without the answer instead of waiting forever: questions to the player time out (180 s in the ask-player path) and the bot falls back to its earlier behavior | design + one setting | `agent/escalation.py:5-9`; `agent/agent.py:930` |
| Optional services can fail without stopping the bots: the state compressor, the external model and the skill author are all best-effort | design | `agent/nn_compressor.py:3-14`; `agent/l5.py:3-5`; `agent/skill_author.py:24-26` |
| A slow server can't hang the bot-control API: every route goes through one bounded-wait wrapper that returns 503 instead of hanging | design | `M/api/BoundedHandler.java` (header); routes `M/api/HttpApiServer.java:107-128` |

Tests that exist (counted with grep; whether they pass was **not** run for this file): 4 Java test
classes with 43 `@Test` methods, all on the API and health layer (`src/test/.../api/`); 37 Python
`test_` functions in 2 files (`agent/tests/test_health_readiness.py` 25, `agent/task_d_fixes_test.py`
12, which tests chat classification); and `agent/rl_reward_test.py`, a script-style test of the reward
function using `check()` calls rather than `test_` functions. The planner and the skill engine have no tests in the
public repo, so don't call them "well tested".

## 3. Architecture

### 3.1 Components

| Component | What it does | Evidence |
|---|---|---|
| **Mod (Java, inside the server)** | Spawns bots as server players, runs their behaviors every tick, and exposes an HTTP API for the agent. | `M/AIPlayerMod.java:177` (`onServerTick`); `M/bot/BotPlayer.java:502` |
| BotBrain | One per bot. Holds the current directive, picks the matching behavior, and drives it one tick at a time until it reports success, failure or cancellation. | `M/brain/BotBrain.java:72-124` |
| SelfPreservation | A reflex layer that runs before the behavior each tick and can take over, for example to keep the bot alive. | `M/brain/BotBrain.java:79` |
| Behaviors | One Java class per kind of work (38 files in `brain/behavior/`), plus low-level actions (`actions/`, e.g. `MineBlockAction`, `CraftAction`). | `M/brain/behavior/`, `M/actions/` |
| Skill engine | Declarative skills: a JSON tree of `sequence` / `fallback` / `loop` / `if` / skill-reference / directive nodes, interpreted by `SkillBehavior` one action at a time. | `M/brain/skill/SkillNode.java:36`; `M/brain/behavior/SkillBehavior.java:1-40` |
| HTTP API | Routes for bots, directives, skills, containers, telemetry and server lookups. Optional `X-Api-Key` auth. | `M/api/HttpApiServer.java:107-128, 148-149` |
| **Agent (Python, one process, one thread per bot)** | Reads chat and world state, plans, sends directives to the mod, and checks results. | `agent/agent.py:152` (`BotRunner`), `:2584` (`_loop`), `:4134` (`run`), `:4262` |
| Skill matcher | Matches plain-text orders to a known seed skill in code, with no model call. It refuses rather than guesses. | `agent/skill_matcher.py:1-23, 388` |
| L2 orchestrator | Runs a task: plan once, then execute subtask by subtask, retrying or re-planning on failure. | `agent/plan_orchestrator.py:1-14, 193`; called at `agent/agent.py:1360` |
| L3 planner | Local model calls: `call_plan` (once per task), `call_exec` (per subtask, produces directives), `call_replan` (fallback). | `agent/l3_planner.py:1-11, 398, 888, 983` |
| L4 escalation | Puts a question in the player's in-game inbox and blocks the plan until the player answers or the wait times out. | `agent/escalation.py:1-15, 39` |
| L5 external model | One stateless advisory call to a stronger hosted model, made only when the player chooses it, using the player's own API key. Its answer comes back to the player for approval. | `agent/l5.py:1-8, 24`; `agent/escalation.py:11-15` |
| Skill author | Off the live loop: mines finished plans from the trajectory log, asks a stronger model to generalize 2–4-step routines into parameterized skills, and registers them through the mod's `/skills` endpoint, which validates but doesn't run them. | `agent/skill_author.py:1-27, 345` |
| Memory | Semantic memory with embeddings (`nomic-embed-text`), plan memory and a plan archive, sessions, waypoints. | `agent/semantic_memory.py:24, 72`; `agent/plan_memory.py`; `agent/plan_store.py` |
| Task board | A shared queue for several bots: an order is split into subtasks that bots claim by specialization. | `agent/taskboard.py` (header) |
| Learning pipeline | The trajectory log records every planner call with its outcome. A deterministic reward function and DPO preference pairs are built from it, and there is a training script for the planner. | `agent/trajectory_log.py:1-12`; `agent/rl_reward.py:1-14`; `agent/build_dpo_dataset.py:1-12`; `agent/train_dpo.py:1-10` |
| State compressor client | An optional background client that sends world state to a separate compression service and caches a short situation summary for the planner. Off the hot path. | `agent/nn_compressor.py:1-18`; used at `agent/agent.py:1090` |
| Dashboard | A FastAPI server (REST + WebSocket) in a daemon thread next to the agent loop, serving a React/Vite/Tailwind app. | `agent/dashboard/server.py:1-6`; `agent/frontend/` |

### 3.2 Decision tiers (L1–L5)

The code names its layers L1 to L5 (see the docstrings cited above). From fastest and cheapest to
slowest and most expensive:

1. **L1, the mod (Java, every server tick).** Executes one directive or skill and handles reflexes. No model.
2. **L2, the orchestrator (Python, deterministic).** Owns the plan, moves through the subtasks, decides
   whether each is done (world state first), and retries or re-plans. The skill matcher sits in front
   of it: an order that matches a known skill skips the model entirely.
3. **L3, the local planner model.** Writes the plan and turns each subtask into directives. It runs on
   local hardware.
4. **L4, the player.** When the system shouldn't decide alone (ambiguous items, an explicit "ask the
   player"), it asks in the player's inbox and waits, with a timeout.
5. **L5, an external model.** Only when the player chooses it for a question. Its answer goes back to
   the player for approval and never flows down to the bots unreviewed.

Off the live loop, a stronger model (the **skill author**) turns successful routines into reusable skills.

### 3.3 Data and control flow (diagram 1: the whole system)

```
Player chat ──► Mod (server) ──HTTP──► Agent: BotRunner._loop  (agent.py:2584)
                                        │  observe chat + world state
                                        │  skill_matcher.match(text) ──hit──► SKILL directive
                                        │        └─miss──► L2 execute_task (plan_orchestrator.py:193)
                                        │                    ├─ L3 call_plan / call_exec / call_replan
                                        │                    ├─ criteria_eval (world state first)
                                        │                    └─ L4 escalation.ask ─► player inbox ─(opt.)─► L5
                                        ▼
                     POST /bot/{name}/directive  (agent/api.py:428-442)
                                        ▼
Mod: BotBrain.tick() every server tick (BotBrain.java:72) ─► Behavior / SkillBehavior ─► world
                                        │
            progress + result ◄── GET /bot/{name}/directive (agent/api.py:45)
Side channels: trajectory_log ─► skill_author ─► POST /skills ; dashboard (FastAPI + React)
```

### 3.4 Close-up (diagram 2): "the model plans, the code plays"

In the public repo, this loop is **skills and directives**:

1. **Plan (model, slow, once).** L3 turns an order into a plan and the plan's subtasks into directives
   (`l3_planner.py:398, 888`). Off the loop, the skill author writes whole reusable skills as JSON trees
   (`skill_author.py:1-27`).
2. **Check before running.** The mod validates a skill before storing it: known directive types, no
   self-reference, a depth cap of 64 (`SkillValidator.java:24-85`, `SkillRegistry.java`). Registering a
   skill never runs it.
3. **Play (code, fast, every tick).** `BotBrain.tick()` hands the directive to its behavior. For a
   SKILL directive, `SkillBehavior` walks the tree on a stack of frames, starting one child behavior per
   leaf and driving it tick by tick until it settles (`SkillBehavior.java:1-40`).
4. **Bounded.** Loops carry `max_iterations`, with at most 32 nested skill calls and at most 500
   actions per run (`SkillBehavior.java:38-39`).
5. **Report.** The result and progress counters come back over the API. L2 checks the world
   (`criteria_eval.py`) and decides whether to move on, retry or re-plan (`plan_orchestrator.py`).
   Each planner call and its outcome goes to the trajectory log, which feeds new skills and the
   preference data.

The point to make: the model is called once per plan or subtask, not once per game tick. The
fast loop is plain code that can be read, validated and bounded.

## 4. Prior work to credit

The repo's code does **not** cite any of these. Present them as related work, not as dependencies or
as the basis of the design.

- **Voyager** (Wang et al., 2023, "Voyager: An Open-Ended Embodied Agent with Large Language Models").
  An LLM agent in Minecraft that builds a library of reusable skills from experience. The skill
  author here follows the same idea. Difference: Voyager's skills are JavaScript programs run
  through Mineflayer; here they are declarative, validated JSON trees run inside the server.
- **Mineflayer.** The common JavaScript bot library that connects to a server as a network client.
  AI Player does **not** use it. Its bots are server-side player entities. Mention it only as a
  contrast.
- **Behavior trees** (the sequence/fallback composition used in game AI and robotics). The skill
  node types `sequence` and `fallback` follow that pattern.
- **DPO**: Rafailov et al., 2023, "Direct Preference Optimization". The training script uses it via
  Hugging Face TRL's `DPOTrainer` (`agent/train_dpo.py:1-10`).
- Tools: NeoForge (mod loader), Ollama (local model serving, `agent/config.py:69`), FastAPI,
  React/Vite/Tailwind, PostgreSQL with vector embeddings for memory (`agent/semantic_memory.py:54-64`).

## 5. Must NOT claim

- **No speeds, success rates or win rates.** Nothing in the repo measures them, including any
  latency per tick, tasks per hour, planner accuracy or "N% fewer model calls".
- **No results from the learning pipeline.** The DPO dataset builder, reward and training script
  exist. Don't say the planner was trained, improved, or by how much. Don't name the training
  hardware.
- **Not "fully autonomous" or "self-improving"** as a measured fact. Say the skill author is
  *designed* to turn successful routines into skills.
- **Don't call the planner or skill engine "well tested".** The public tests cover the API/health
  layer, chat classification and the reward function only (section 2).
- **Nothing that is only in the private tree.** That means no JavaScript or sandboxed agent scripts,
  no script runner, no per-bot code-hour caps, and no "players can read bot scripts". None of this
  is in the public repo.
- **No other projects.** No hive / fleet-bot mod, no other games, no other services. The public
  agent's code mentions squads, fleets and one "hive" skill name in passing (`agent/agent.py:3820-3832`).
  Describe only multi-bot orders and the task board, not any separate project.
- **No infrastructure details.** No cluster, host or node names, no internal URLs, no GPU models, no
  deployment layout, keys or how the server is run. The public README gives the setup a reader needs.
- **No model names as fixed facts.** The local and external models are settings (`agent/config.py:69,
  81-83`). It's fine to say "a local model via Ollama" and "an optional hosted model the player
  enables with their own key". Don't present a specific model as part of the design.
- **Nothing about debugging stories, incidents or daily operations** (owner's rule for posts).

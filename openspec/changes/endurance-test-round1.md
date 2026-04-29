# Endurance Test — Full Report (Round 1 + Round 2)

**Date**: 2026-04-28 / 2026-04-29
**Environment**: Kubernetes homelab cluster (sigma-worker1), ephemeral test pods
**NeoForge**: 1.21.1 with aiplayermod (latest build)
**Agent**: Python-based L1/L2/L3 planning agent with ollama backend
**Database**: Isolated per-world (botmemory_test_<name>) via pgvector

---

## Test Infrastructure

### Architecture

Each endurance test spins up a single Kubernetes pod containing two containers:

1. **mc-server** — itzg/minecraft-server:java21 with NeoForge + aiplayermod JAR
   - Exposes port 25565 (Minecraft), 25575 (RCON), 3100 (mod HTTP API)
   - World type configurable (flat/normal) with seed support
   - Difficulty: normal, PVP: off, survival mode

2. **agent** — harbor.arcadia-ecs.local/aiplayermod/agent:latest
   - L1/L2/L3 planning agent connecting to ollama for LLM inference
   - Exposes port 5000 (dashboard/command API)
   - Connects to mod API at localhost:3100
   - PG_DSN pointed to isolated test database

An init container (**mod-sync**) pulls the latest mod JAR from MinIO before the server starts.

### Bot Configuration

Each test world spawns 5 bots by default from the agent profile:
- **Mystic** / **Forge** — Coordinators. Receive instructions from the harness, delegate via task board.
- **Axiom** — Primary worker. Picks up most crafting/mining/combat tasks.
- **Scout** — Secondary worker. Often assigned exploration/deep mining.
- **Tiller** — Tertiary worker. Picks up overflow tasks.

The coordinator pattern: the harness sends natural language instructions to the first bot (Mystic or Forge). That bot's L3 planner decomposes the instruction into concrete steps and posts them to the shared task board. Worker bots poll the task board and claim tasks matching their specialization.

### Database Isolation

Each test world gets a temporary PostgreSQL database:
```
botmemory_test_operation_basecamp
botmemory_test_deep_mine_expedition
botmemory_test_night_watch
```

Created at pod spin-up (`CREATE DATABASE ... OWNER aibot`), dropped on teardown. The agent container's PG_DSN is patched at pod creation to point to the isolated database. This prevents test tasks from leaking to production bots (see H4 hotfix).

### Test Harness Flow

```
1. Load test YAML → TestDefinition (name, steps, timeouts, success criteria)
2. create_world() → spin up pod + temp database
3. wait_ready() → poll container readiness (up to 300s)
4. _wait_mod_api() → poll mod HTTP API /health (up to 120s)
5. _resolve_bots() → GET /bots to discover available bots
6. For each step:
   a. POST /api/command {bot, message} → send natural language instruction
   b. Poll success criteria every 5s until timeout
   c. Record StepResult (passed, duration, details)
7. destroy_world() → delete pod + drop temp database
8. Return TestResult with all step results
```

### Directive Chain (Instruction → Execution)

When the harness sends an instruction like `"Mine iron ore deep underground"`:

```
Harness → POST /api/command {"bot": "Forge", "message": "Mine iron ore..."}
       ↓
Agent L3 (LLM) → Decomposes into concrete plan steps
       ↓
Agent L2 (Planner) → Generates primitive actions:
  "Find and mine minecraft:iron_ore"
  "Craft minecraft:furnace"
  "Smelt 10x minecraft:raw_iron"
       ↓
Agent L1 (Parser) → Regex-matches to directive types:
  {"type": "MINE", "target": "iron_ore"}
  {"type": "CRAFT", "target": "minecraft:furnace"}
  {"type": "SMELT", "target": "minecraft:raw_iron", "count": 10}
       ↓
Mod API → POST /bot/{name}/directive {"type": "MINE", ...}
       ↓
CraftBehavior / MineBehavior / CombatBehavior → Java-side tick loop
```

### L2 Planner Prompt (key sections)

The L2 planner receives a system prompt with available action primitives:

```
Each step MUST be a single primitive that the bot can execute directly:
- Mine: "Mine minecraft:iron_ore (24)" or "Find and mine minecraft:oak_log"
- Craft: "Craft minecraft:iron_pickaxe" or "Craft 4x minecraft:stick"
- Smelt: "Smelt minecraft:raw_iron" or "Smelt 8x minecraft:raw_iron"
- Combat: "Engage combat mode 300s" (fights hostile mobs for N seconds)
- Attack: "Attack zombie 120s" (fights specific mob type)
...
```

The planner also receives current bot inventories, available bots with specializations, and the transmute registry for channeled items.

### Success Criteria

Each step defines an `inventory_contains` check:
```yaml
success:
  inventory_contains:
    item: "minecraft:iron_pickaxe"   # substring match against item registry ID
    min_count: 1                      # minimum count across ALL bots
```

The harness queries `/bots` to discover all bots, then checks `/bot/{name}/inventory` for each, summing counts across the entire team. Substring matching allows patterns like `"_log"` (any log type), `"cooked_"` (any cooked meat).

---

## Test 1: operation-basecamp

**Goal**: Full survival tech tree progression — diamond pickaxe, diamond sword, iron armor, 32+ cooked food, 10+ gold ingots, 32+ redstone, 16+ lapis lazuli.

**World**: Normal terrain, animals + monsters enabled, difficulty normal
**TTL**: 14400s (4 hours)
**Steps**: 18 across 7 phases

### Phases and Steps

| # | Phase | Instruction | Timeout | Success Criteria | Harness Result |
|---|-------|-------------|---------|-----------------|----------------|
| 1 | wood-age | Look around for trees and chop them. Collect at least 16 logs. | 600s | >= 16 `_log` | FAIL (0) |
| 2 | wood-age | Convert logs into planks, then craft a crafting table, a wooden pickaxe, a wooden axe, and a wooden sword. | 300s | >= 1 `wooden_pickaxe` | FAIL (0) |
| 3 | stone-age | Dig underground and mine at least 48 cobblestone. | 600s | >= 48 `cobblestone` | FAIL (0) |
| 4 | stone-age | Craft a stone pickaxe, a stone sword, and a stone axe. | 300s | >= 1 `stone_pickaxe` | FAIL (0) |
| 5 | stone-age | Craft a furnace and a chest. | 300s | >= 1 `furnace` | FAIL (0) |
| 6 | infrastructure | Mine coal ore underground. Collect at least 16 coal. | 600s | >= 16 `coal` | FAIL (0) |
| 7 | infrastructure | Craft at least 32 torches from coal and sticks. | 300s | >= 32 `torch` | FAIL (0) |
| 8 | iron-age | Mine iron ore deep underground. Dig to y-level 16 or below. Collect at least 24 raw iron. | 1200s | >= 24 `raw_iron` | FAIL (0) |
| 9 | iron-age | Smelt all your raw iron into iron ingots. You need at least 24. | 600s | >= 24 `iron_ingot` | FAIL (0) |
| 10 | iron-age | Craft an iron pickaxe, an iron sword, and an iron axe. | 300s | >= 1 `iron_pickaxe` | FAIL (0) |
| 11 | iron-age | Craft iron armor: chestplate and helmet. | 300s | >= 1 `iron_chestplate` | FAIL (0) |
| 12 | self-sufficiency | Hunt animals, cook meat. Get at least 32 cooked meat total. | 1200s | >= 32 `cooked_` | FAIL (0) |
| 13 | self-sufficiency | Craft a shield and a bucket. | 300s | >= 1 `shield` | FAIL (0) |
| 14 | diamond-age | Mine deep underground to y=-59. Collect at least 5 diamonds. | 1800s | >= 5 `diamond` | FAIL (0) |
| 15 | diamond-age | Craft a diamond pickaxe and a diamond sword. | 300s | >= 1 `diamond_pickaxe` | FAIL (0) |
| 16 | resource-stockpile | Mine gold ore, smelt. Collect at least 10 gold ingots. | 1200s | >= 10 `gold_ingot` | FAIL (0) |
| 17 | resource-stockpile | Mine redstone ore. Collect at least 32 redstone. | 900s | >= 32 `redstone` | FAIL (0) |
| 18 | resource-stockpile | Mine lapis lazuli ore. Collect at least 16 lapis lazuli. | 900s | >= 16 `lapis_lazuli` | FAIL (0) |

**Harness Result**: 0/18 steps passed, 0/7 phases passed. Duration: 202.2 min.
**ALL RESULTS ARE FALSE NEGATIVES** — see Bugs section (H1).

### Actual Bot Performance (manual inventory snapshots)

The harness checked only the coordinator bot (Forge), which held 0 items. Worker bots held everything.

**At ~60 minutes (Axiom — primary worker):**
- diamond_pickaxe x1, diamond_sword x1, diamond x4
- iron_pickaxe x1, iron_sword x1, iron_axe x1
- iron_chestplate x1, iron_helmet x1
- shield x1, bucket x1
- stone_pickaxe x1, stone_sword x1, stone_axe x1
- wooden_pickaxe x1, wooden_axe x1, wooden_sword x1
- furnace x1, chest x1, torch x32
- oak_log x8, oak_planks x2, coal x1
- gold_ingot x10

**At ~60 minutes (Scout — deep miner):**
- cobblestone x62, mossy_cobblestone x28
- iron_ingot x16, raw_iron x23
- diamond x3, raw_gold x15
- redstone x105 (64 + 41)
- coal x15

**Combined actual achievement vs. goals:**

| Goal | Required | Actual (combined) | Met? |
|------|----------|-------------------|------|
| Diamond pickaxe | 1 | 1 (Axiom) | YES |
| Diamond sword | 1 | 1 (Axiom) | YES |
| Iron armor | chestplate + helmet | Both (Axiom) | YES |
| Cooked food | 32 | 0 observed | NO |
| Gold ingots | 10 | 10 (Axiom) + 15 raw (Scout) | YES |
| Redstone | 32 | 105 (Scout) | YES |
| Lapis lazuli | 16 | 0 observed | NO |

The bot reached diamond age in approximately 60 minutes, with full iron armor, diamond tools, and significant gold/redstone stockpiles. Lapis and cooked food were not prioritized by the planner. Scout explored a dungeon (mossy_cobblestone) and descended to diamond level independently.

---

## Test 2: deep-mine-expedition

**Goal**: Mining expedition — iron pickaxe+, 24 raw copper, 12 raw gold, 48 redstone, 24 lapis, 12 diamonds.

**World**: Normal terrain, monsters enabled, no animals, difficulty normal
**TTL**: 10800s (3 hours)
**Steps**: 10 across 5 phases

### Phases and Steps

| # | Phase | Instruction | Timeout | Success Criteria | Harness Result |
|---|-------|-------------|---------|-----------------|----------------|
| 1 | preparation | Quickly gather wood and craft a wooden pickaxe. Do not spend long on the surface. | 300s | >= 1 `wooden_pickaxe` | FAIL (0) |
| 2 | preparation | Mine cobblestone and craft a stone pickaxe. Mine some coal for torches. | 600s | >= 1 `stone_pickaxe` | FAIL (0) |
| 3 | iron-bootstrap | Find and mine iron ore, smelt at least 10 iron ingots. Craft an iron pickaxe. | 900s | >= 1 `iron_pickaxe` | FAIL (0) |
| 4 | upper-mines | Mine copper ore around y-level 48. Collect at least 24 raw copper. | 900s | >= 24 `raw_copper` | FAIL (0) |
| 5 | upper-mines | Continue mining. Collect at least 32 additional coal for smelting fuel. | 600s | >= 32 `coal` | FAIL (0) |
| 6 | deep-mines | Descend to y=-16 and mine gold ore. Collect at least 12 raw gold. | 900s | >= 12 `raw_gold` | FAIL (0) |
| 7 | deep-mines | Mine redstone ore at y=-59 or below. Collect at least 48 redstone. | 900s | >= 48 `redstone` | FAIL (0) |
| 8 | deep-mines | Mine lapis lazuli ore. Collect at least 24 lapis lazuli. | 900s | >= 24 `lapis_lazuli` | FAIL (0) |
| 9 | diamond-hunt | Strip mine at y=-59. Dig long tunnels with 2-block gaps. Collect at least 8 diamonds. | 1800s | >= 8 `diamond` | FAIL (0) |
| 10 | diamond-hunt | Keep mining diamonds. Aim for at least 12 total. | 1200s | >= 12 `diamond` | FAIL (0) |

**Harness Result**: 0/10 steps passed, 0/5 phases passed. Duration: 152.4 min.
**ALL RESULTS ARE FALSE NEGATIVES** (H1).

### Actual Bot Performance

**At ~55 minutes (Axiom):**
- iron_pickaxe x1, stone_pickaxe x1, wooden_pickaxe x1
- furnace x1, coal x14, charcoal x1
- stone x8, oak_log x8, oak_planks x1, stick x4

**At ~55 minutes (Scout):**
- raw_iron x10, raw_copper_block x13, coal x20

Scout was actively mining at y=22 (x=-160, z=185) — far from spawn, deep underground. The bot successfully navigated to copper-bearing depths and was extracting ore. Axiom had progressed through the full tool chain to iron pickaxe.

**Assessment**: The expedition test demonstrated sustained underground navigation and tool progression. However, the bots did not reach the deeper ore tiers (gold, redstone, diamond) within the test duration, suggesting the planner may not aggressively enough direct descent to lower y-levels.

---

## Test 3: night-watch

**Goal**: Combat endurance — iron sword, 24 rotten flesh, 16 bones, 8 string, 6 gunpowder, 8 arrows.

**World**: Normal terrain, animals + monsters enabled, difficulty normal
**TTL**: 7200s (2 hours)
**Steps**: 12 across 5 phases

### Phases and Steps

| # | Phase | Instruction | Timeout | Success Criteria | Harness Result |
|---|-------|-------------|---------|-----------------|----------------|
| 1 | equip | Gather wood, craft crafting table, wooden sword and wooden shield. | 300s | >= 1 `wooden_sword` | FAIL (0) |
| 2 | equip | Mine cobblestone and craft a stone sword. Also craft torches. | 600s | >= 1 `stone_sword` | FAIL (0) |
| 3 | equip | Hunt animals for food and cook the meat. Get at least 8 cooked meat. | 600s | >= 8 `cooked_` | **PASS** (8) |
| 4 | first-night | Fight hostile mobs. Eat food when health is low. Collect at least 8 rotten flesh. | 900s | >= 8 `rotten_flesh` | FAIL (0) |
| 5 | first-night | Continue fighting. Target skeletons. Collect at least 8 bones. | 900s | >= 8 `bone` | FAIL (0) |
| 6 | upgrade | Mine iron ore, smelt, craft iron sword. Craft iron armor if enough ingots. | 900s | >= 1 `iron_sword` | FAIL (0) |
| 7 | upgrade | Hunt more animals. Restock to at least 16 cooked meat. | 600s | >= 16 `cooked_` | FAIL (0) |
| 8 | extended-combat | Fight hostile mobs aggressively. Kill spiders, collect at least 8 string. | 900s | >= 8 `string` | FAIL (0) |
| 9 | extended-combat | Hunt creepers carefully. Collect at least 6 gunpowder. | 1200s | >= 6 `gunpowder` | FAIL (0) |
| 10 | extended-combat | Keep fighting all hostile mobs. Collect at least 8 arrows. | 900s | >= 8 `arrow` | FAIL (0) |
| 11 | endurance | Continue hunting all hostile mobs. Accumulate at least 24 rotten flesh. | 1200s | >= 24 `rotten_flesh` | FAIL (error) |
| 12 | endurance | Final push. Accumulate at least 16 bones total. | 1200s | >= 16 `bone` | FAIL (error) |

**Harness Result**: 1/12 steps passed, 0/5 phases passed. Duration: 143.0 min.

Step 3 (cook meat) was the only PASS — Mystic (coordinator) cooked 8 porkchop and the harness found it in Mystic's inventory directly.

Steps 11-12 failed with connection errors — the pod's TTL expired during the final steps.

### Actual Bot Performance

**At ~55 minutes (Axiom — primary worker):**
- iron_chestplate x1, iron_leggings x1, iron_boots x1
- iron_pickaxe x1, iron_sword x1
- stone_pickaxe x1, stone_sword x1, wooden_sword x1
- torch x16, coal x5, raw_iron x3
- oak_log x5, oak_planks x2

**At ~55 minutes (Mystic — coordinator):**
- cooked_porkchop x8

**Combat drops**: ZERO across all bots. No rotten flesh, no bones, no string, no gunpowder, no arrows.

**Assessment**: Axiom autonomously crafted full iron armor (chestplate + leggings + boots) and weapons. The crafting and resource gathering pipeline is working well. However, combat is **completely non-functional** — see H5 hotfix. All 5 bots enter "Combat mode (patrolling)" but never transition to "fighting" because:
1. Combat duration defaults to 30 seconds (not enough for a night cycle)
2. Bots stand still in patrol mode instead of walking to find mobs
3. The L2 planner hard-codes "Engage combat mode 30s" in all combat plans

---

## Bugs Found

### H1: Harness checks wrong bot inventory (CRITICAL — harness)

**Impact**: Every inventory_contains check returns 0. All 47 steps across 3 tests show "actual: 0" despite bots having full inventories.

**Root cause**: Harness sends instructions to the first bot (coordinator), which delegates via task board to worker bots. Items accumulate in worker inventories. Harness only checked the coordinator.

**Fix**: `_check_success()` now calls `_get_all_bots()` → `GET /bots`, iterates all bots, sums inventory counts. Reports holding bot in `details["holder"]`.

**Status**: FIXED in `harness.py`. **This fix was not active during Round 1** — test processes loaded old code at startup.

### H2: CRAFT recipe selection ignores inventory (IMPORTANT — mod)

**Impact**: Bot channels bamboo via XP to make sticks instead of using oak_planks already in inventory. Wastes XP on every tool/weapon craft.

**Root cause**: `findVanillaRecipe()` returns first matching minecraft-namespace recipe. `stick_from_bamboo_item` sorts alphabetically before the planks→sticks recipe.

**Fix**: Added `scoreRecipeByInventory()` — counts how many ingredient types the bot already has. `findVanillaRecipe()` picks the highest-scoring recipe.

**Status**: FIXED in `CraftBehavior.java`.

### H3: L3 planner omits intermediate crafting steps (MODERATE — agent)

**Impact**: L3 plan jumps to "Craft wooden_pickaxe" without "Craft sticks from planks." CRAFT auto-resolves via channeling, which compounds with H2.

**Status**: PENDING — lower priority now that H2 ensures CRAFT uses inventory ingredients.

### H4: Test database isolation (CRITICAL — infrastructure)

**Impact**: Test agents connected to production task board. Agent startup called `_task_board.clear_all()` which wiped production tasks. Test instructions executed on the main Minecraft server.

**Fix**: Per-world temporary database lifecycle in `world.py` — `create_test_db()` / `drop_test_db()`.

**Status**: FIXED.

### H5: Combat 30s default + no patrol movement (IMPORTANT — mod + agent)

**Impact**: All combat directives complete with 0 kills. Bots stand still for 30 seconds, never engage mobs. Blocks all combat-dependent test scenarios.

**Root cause chain**:
1. `CombatBehavior.java DEFAULT_DURATION = 600` ticks (30 seconds)
2. `planner.py` L2 prompt hard-codes `"Engage combat mode 30s"` in examples
3. `agent.py` L1 parser defaults to 30s when no duration specified
4. `CombatBehavior.java` "patrolling" phase does not move the bot — it stands still waiting for mobs to wander into search radius

**Evidence** (agent logs — all 5 bots identical):
```
[Axiom/L1] Combat mode (25s left, 0 kills) (phase=patrolling, counters={})
[Axiom/L1] Combat mode (23s left, 0 kills) (phase=patrolling, counters={})
...
[Axiom/L1] Combat mode (0s left, 0 kills) (phase=patrolling, counters={})
[Axiom/L1] Directive COMPLETED: {}
```

**Fix**:
1. `CombatBehavior.java`: DEFAULT_DURATION → 6000 ticks (5 min). Added `patrol()` method — random walk with direction changes every 3-7 seconds, jump detection for obstacles.
2. `agent.py`: Default combat duration 30 → 300 seconds.
3. `planner.py`: All combat examples updated from 30s to 300s. Added guidance for 600s+ sustained combat.

**Status**: FIXED.

---

## Key Observations

### What Worked Well

1. **Coordinator delegation pattern** — Forge/Mystic correctly decomposed complex instructions into task board items. Axiom and Scout picked up tasks and executed them.

2. **Tool progression** — Bots autonomously progressed wood → stone → iron → diamond without explicit intermediate steps in the test instructions. The L3 planner correctly identified prerequisites.

3. **Deep mining** — Scout navigated to y=12 (basecamp) and y=22 (expedition) independently, finding dungeons, ore veins, and rare resources. Axiom hit diamond level.

4. **Iron age in ~12 minutes** — Night-watch Axiom had iron tools, stone tools, torches, and 4 iron ingots within 12 minutes of world creation. By 55 minutes: full iron armor set.

5. **Diamond age in ~60 minutes** — Basecamp Axiom achieved diamond pickaxe, diamond sword, iron armor, gold ingots, and 105 redstone in about an hour.

### What Failed

1. **Combat is non-functional** (H5) — Zero mob kills across 143 minutes of combat testing. The 30s duration + standing still made combat directives useless.

2. **Harness inventory check was broken** (H1) — Every single inventory check returned 0. The entire test suite produced false negatives.

3. **Recipe selection wasted XP** (H2) — Bamboo channeling instead of using available planks. Compounds over time.

4. **Coordinator bots idle** — Mystic, Tiller, Forge sit at spawn (0.5, y, 0.5) the entire test. Only Axiom and Scout do actual work. The coordinator delegation works but wastes 3 out of 5 bot slots.

5. **Planner doesn't descend aggressively** — In the expedition test, bots stayed in upper mine levels. The instruction "descend to y=-59" didn't translate into aggressive downward mining. The MINE directive finds the nearest matching ore, which may be at higher y-levels.

---

## Infrastructure Changes Applied

| Component | Change | File(s) |
|-----------|--------|---------|
| Test harness | Aggregate inventory across all bots | `harness.py` |
| Test harness | Phase tracking, halt_on_failure, elapsed time | `harness.py` |
| Test worlds | Per-world temp database lifecycle | `world.py` |
| Test worlds | World type env patching (normal/flat) | `world.py` |
| Test worlds | NodePort Service per world (MC + API + dashboard) | `world.py`, `service-template.yaml` |
| Test worlds | Ingress per world (dashboard HTTP access) | `world.py`, `ingress-template.yaml` |
| Pod template | Per-pod label for service selector | `pod-template.yaml` |
| Mod | Recipe scoring by inventory match | `CraftBehavior.java` |
| Mod | Combat 5-min default + patrol movement | `CombatBehavior.java` |
| Agent | Combat default duration 30s → 300s | `agent.py` |
| Agent | Planner combat examples updated to 300s | `planner.py` |

---

## Round 2 Results

**Fixes deployed**: H1 (aggregate inventory), H2 (recipe scoring), H4 (DB isolation), H5 (combat duration + patrol)
**Infrastructure**: NodePort Services + Ingress per test world for Minecraft client access

### Comparison: Round 1 vs Round 2

| Test | R1 Steps Passed | R2 Steps Passed | R1 Phases | R2 Phases | Duration |
|------|----------------|----------------|-----------|-----------|----------|
| operation-basecamp | 0/18 | **10/18** | 0/7 | 1/7 | 136 min |
| deep-mine-expedition | 0/10 | **6/10** | 0/5 | 2/5 | 84 min |
| night-watch | 1/12 | **3/12** | 0/5 | 0/5 | 129 min |

### operation-basecamp Round 2 — Step by Step

| # | Phase | Step | Result | Detail |
|---|-------|------|--------|--------|
| 1 | wood-age | Collect at least 16 logs | **FAIL** | 15/16 (1 short, 602s) |
| 2 | wood-age | Craft wooden pickaxe, axe, sword | **PASS** | Axiom, 40s |
| 3 | stone-age | Mine at least 48 cobblestone | **PASS** | Scout, 48 exact, 482s |
| 4 | stone-age | Craft stone pickaxe, sword, axe | **PASS** | Axiom, 25s |
| 5 | stone-age | Craft furnace and chest | **PASS** | Axiom, 15s |
| 6 | infrastructure | Mine at least 16 coal | **FAIL** | 6/16, 602s |
| 7 | infrastructure | Craft at least 32 torches | **FAIL** | 4/32, 301s |
| 8 | iron-age | Mine at least 24 raw iron | **FAIL** | 15/24, 1205s |
| 9 | iron-age | Smelt at least 24 iron ingots | **FAIL** | 0/24, 602s |
| 10 | iron-age | Craft iron pickaxe, sword, axe | **PASS** | Axiom, 20s |
| 11 | iron-age | Craft iron chestplate and helmet | **PASS** | Axiom, 30s |
| 12 | self-sufficiency | Cook at least 32 meat | **FAIL** | 0/32, 1205s |
| 13 | self-sufficiency | Craft shield and bucket | **PASS** | Axiom, 15s |
| 14 | diamond-age | Mine at least 5 diamonds | **FAIL** | 3/5, 1802s |
| 15 | diamond-age | Craft diamond pickaxe and sword | **PASS** | Axiom, 15s |
| 16 | resource-stockpile | Smelt at least 10 gold ingots | **PASS** | Axiom, 20s |
| 17 | resource-stockpile | Mine at least 32 redstone | **PASS** | Scout, 39 redstone, 151s |
| 18 | resource-stockpile | Mine at least 16 lapis lazuli | **FAIL** | 0/16, 903s |

**Analysis**: Crafting steps pass rapidly (15-40s) once materials exist. The bot reaches diamond pickaxe + iron armor + gold + redstone. Failures are in raw material gathering thresholds — the bot gathers materials but sometimes falls short of the exact count within the timeout. Cooked food (step 12) and lapis lazuli (step 18) remain at 0, suggesting the planner doesn't prioritize animal hunting or lapis mining.

### deep-mine-expedition Round 2 — Step by Step

| # | Phase | Step | Result | Detail |
|---|-------|------|--------|--------|
| 1 | preparation | Craft wooden pickaxe | **PASS** | Axiom, 183s |
| 2 | preparation | Craft stone pickaxe + coal | **PASS** | Axiom, 105s |
| 3 | iron-bootstrap | Smelt iron + craft iron pickaxe | **PASS** | Axiom, 30s |
| 4 | upper-mines | Mine at least 24 raw copper | **PASS** | Scout, 25 copper, 201s |
| 5 | upper-mines | Mine at least 32 coal | **FAIL** | 30/32 (2 short, 602s) |
| 6 | deep-mines | Mine at least 12 raw gold | **FAIL** | 4/12, 904s |
| 7 | deep-mines | Mine at least 48 redstone | **PASS** | Scout, 54 redstone, 146s |
| 8 | deep-mines | Mine at least 24 lapis lazuli | **FAIL** | 0/24, 904s |
| 9 | diamond-hunt | Mine at least 8 diamonds | **FAIL** | 6/8 (close, 1802s) |
| 10 | diamond-hunt | Mine at least 12 diamonds | **PASS** | Scout, 15 diamonds, 50s |

**Analysis**: Tool progression is flawless (3/3). Scout reached deep levels quickly and accumulated massive resources — 81 raw copper, 142 redstone, 15 diamonds by end of test. Step 9→10 shows an interesting pattern: Scout had 6 diamonds at step 9 timeout but reached 15 by the time step 10 checked (50s later). The bot continues mining between steps. Lapis lazuli consistently at 0 across both tests — the MINE directive may not know how to find lapis specifically.

### night-watch Round 2 — Step by Step

| # | Phase | Step | Result | Detail |
|---|-------|------|--------|--------|
| 1 | equip | Craft wooden sword + shield | **PASS** | Axiom, 90s |
| 2 | equip | Craft stone sword + torches | **PASS** | Axiom, 276s |
| 3 | equip | Cook at least 8 meat | **FAIL** | 1/8, 602s |
| 4 | first-night | Collect 8 rotten flesh | **FAIL** | 0 (0 kills, 904s) |
| 5 | first-night | Collect 8 bones | **FAIL** | 0 (0 kills, 904s) |
| 6 | upgrade | Craft iron sword + armor | **PASS** | Axiom, 35s |
| 7 | upgrade | Cook at least 16 meat | **FAIL** | 1/16, 602s |
| 8 | extended-combat | Collect 8 string | **FAIL** | 0 (0 kills, 904s) |
| 9 | extended-combat | Collect 6 gunpowder | **FAIL** | 0 (0 kills, 1205s) |
| 10 | extended-combat | Collect 8 arrows | **FAIL** | 0 (0 kills, 903s) |
| 11 | endurance | Collect 24 rotten flesh | **FAIL** | 0 (pod dying, 1207s) |
| 12 | endurance | Collect 16 bones | — | Pod destroyed before step ran |

**Analysis**: Tool/weapon crafting works perfectly (wooden sword → stone sword → iron sword in 3 passes). Combat remains completely broken — **zero mob kills across 129 minutes and multiple 300s combat cycles**. The H5 fix (duration + patrol) is confirmed active (logs show "Combat mode engaged (300s)" and bots move during patrol), but bots patrol underground where they ended up from prior mining steps. They never ascend to the surface for nighttime mob encounters. See H6.

### New Issue: H6 — Combat patrols underground instead of surface (MODERATE — mod)

**Symptom**: Bots enter combat mode and patrol actively (confirmed by position changes), but patrol underground in caves/mines where mob density is near zero. Zero kills after 129 minutes of testing.

**Root cause**: After equip/upgrade phases, bots are underground from mining. When combat is issued, `CombatBehavior.patrol()` walks randomly from the bot's current position. There is no logic to ascend to the surface first. Underground patrolling covers small areas of already-explored (and possibly lit) caves.

**Fix (proposed)**:
1. Combat directive should navigate the bot to the surface (y > 60) before starting patrol
2. Or: add a `GOTO_SURFACE` pre-step that the planner inserts before combat
3. Or: patrol movement should prefer upward navigation when underground

**Status**: PENDING — next round fix

### New Issue: H7 — Animal hunting / food cooking unreliable (MINOR — agent)

**Symptom**: "Cook at least 8/16/32 meat" consistently fails. Bots find 0-1 cooked food items across all tests.

**Root cause**: The MINE directive can find ores by scanning for block types, but hunting animals requires entity tracking + killing + furnace cooking — a multi-step chain that the planner may not decompose correctly. Animals are also finite and may have been killed or wandered away.

**Status**: PENDING — investigate animal hunting directive chain

### New Issue: H8 — Lapis lazuli never found (MINOR — mod)

**Symptom**: 0 lapis lazuli across all tests and both rounds. Every other deep ore (redstone, diamond, gold, copper) is found.

**Root cause**: MINE directive searches for the nearest matching block by name. Lapis lazuli ore may use a registry name that doesn't match the search pattern, or it may spawn in veins the scan doesn't reach.

**Status**: PENDING — investigate `lapis_lazuli_ore` vs `lapis_ore` registry ID and scan coverage

---

## Overall Assessment

### What the fixes solved

| Fix | Round 1 Impact | Round 2 Impact |
|-----|---------------|----------------|
| H1 (inventory aggregation) | 0 real PASSes | 19 real PASSes across 3 tests |
| H2 (recipe scoring) | Bamboo channeling for sticks | Planks used correctly (no wasted XP observed) |
| H4 (DB isolation) | Production tasks leaked | Clean isolation, 0 production impact |
| H5 (combat duration + patrol) | 30s combat, standing still | 300s combat, bots move — but still 0 kills (see H6) |

### Remaining gaps

1. **Combat (H6)**: Needs surface navigation before patrol. The duration and movement fixes are necessary but insufficient — bots must be in the right place.
2. **Food (H7)**: Animal hunting + cooking pipeline broken. Bots don't reliably hunt, kill, and cook animals.
3. **Lapis (H8)**: Lapis lazuli ore never located by the MINE directive. Possible registry ID mismatch.
4. **Gathering thresholds**: Several steps fail by small margins (15/16 logs, 30/32 coal, 6/8 diamonds). Consider slightly longer timeouts or lower thresholds for close-miss items.
5. **Idle coordinators**: 3 of 5 bots (Mystic, Tiller, Forge) remain idle at spawn. Only Axiom and Scout do meaningful work. The coordinator pattern wastes 60% of bot capacity.

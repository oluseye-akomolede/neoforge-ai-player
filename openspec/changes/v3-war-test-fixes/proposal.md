# v3: War-Test Fixes

## Why

The 2026-07-08 live war test ("prepare, enter the nether, kill 200 enemies
each" issued to all 5 bots) surfaced 7 findings. Four bots finished their
plans and one failed outright, but every "success" leaned on unverifiable
criteria, and the failure burned all five attempts on the same invented
directive with no corrective feedback. This change hardens the planning
loop so the same command is machine-verifiable end to end.

## Findings → Fixes

| # | Finding | Fix | Where |
|---|---------|-----|-------|
| 1 | Kill counts unverifiable — "killed 200 enemies" criteria passed via lax L3 fallback judgment; no ground truth existed | Mod `/bot status` now reports `mob_kills` / `deaths` (vanilla Stats). Orchestrator snapshots `plan.meta["kills_at_start"]` at plan creation; new `kill_stat` criteria strategy passes only when `current − baseline ≥ target`. No baseline ⇒ conservative fail with observed count. | `BotPlayer.getStatus()`, `plan_schema.Plan.meta`, `plan_orchestrator`, `criteria_eval._strategy_kills` |
| 2 | Forge invented `EQUIP` directive 3× and failed the plan — kind doesn't exist, retries got no vocabulary feedback | `EQUIP`→`EQUIP_ALL` alias in agent `_repair_directive` and l2-mcp `KIND_ALIASES`; dispatcher intercepts `EQUIP`/`EQUIP_ALL` and calls the mod's bulk-equip endpoint; `EQUIP_ALL` documented in the EXEC prompt's directive reference; l2-mcp flags `unknown_kind:<KIND>` for anything outside `KNOWN_KINDS` so retry prompts name the exact problem | `agent._l3_orchestrator_dispatch`, `plan_orchestrator._repair_directive`, `l3_planner._EXEC_SYSTEM_PROMPT`, `l2-mcp renderers` |
| 3 | Dropped task clauses — some plans omitted the "kill 200" clause entirely (Tiller planned 3 subtasks ending at nether arrival) | PLAN prompt now requires subtasks to cover EVERY action clause ("prepare AND travel AND fight ⇒ all three appear") | `l3_planner._PLAN_SYSTEM_PROMPT` |
| 4 | Wrong-dimension staging — L3 subtasked crafting inside `ae2:spatial_storage` because the dimension list was presented flat | Dimension list now annotated: primary dims plain; everything else marked "special-purpose — do NOT travel here unless the task names it" | `l3_planner._dim_lines` (both PLAN and EXEC prompts) |
| 5 | Stale mob ids — COMBAT targeted `minecraft:pig_zombie` (renamed to `zombified_piglin` in 1.16); L1 matched nothing | `MOB_SYNONYMS` mapping applied to COMBAT targets in agent `_repair_directive` and authoritatively in l2-mcp `normalize_directive` | `plan_orchestrator._MOB_SYNONYMS`, `l2-mcp renderers.MOB_SYNONYMS` |
| 6 | Free-text criteria — L3 wrote criteria like "bot is battle-ready" that no strategy could check, forcing L3-fallback judgment | PLAN prompt lists the 5 machine-checkable criteria forms (inventory / position / dimension / kill-count / block-at) and instructs L3 to prefer them | `l3_planner._PLAN_SYSTEM_PROMPT` |
| 7 | Agent logs were blind — orchestrator INFO lines never appeared, making live diagnosis guesswork | `logging.basicConfig(INFO)` at agent start (urllib3/httpx capped at WARNING) | `agent.py` |

## What Changes

- **api-http**: `/bot status` response gains `mob_kills` (int) and `deaths`
  (int); `-1` sentinel when stats are unavailable.
- **l3-spec-driven-planning**:
  - Plan schema gains `meta` (free-form execution metadata dict, persisted).
  - Criteria contract: plans SHOULD use one of the five checkable forms;
    kill-count criteria are verified as a delta against
    `meta["kills_at_start"]` via the new `kill_stat` strategy (ordered
    between `world_state` and `result_text`).
  - Plans MUST cover every action clause of the task.
  - Directive vocabulary: `EQUIP_ALL` is a first-class directive; `EQUIP`
    is an accepted alias.
- **l2-mcp-translation-layer**: `normalize_directive` additionally applies
  `KIND_ALIASES`, flags `unknown_kind:<KIND>`, and canonicalizes COMBAT
  targets through `MOB_SYNONYMS`. All translation-only — flags, never
  resolves, ambiguity.

## Non-Goals

- No new decision-making in L2 (translation-layer purity holds).
- No mod-side kill attribution beyond vanilla stats (per-mob-type kill
  deltas deferred).
- Hive-mod mirrors deferred until aiplayermod findings settle (per
  direction: test only with aiplayermod).

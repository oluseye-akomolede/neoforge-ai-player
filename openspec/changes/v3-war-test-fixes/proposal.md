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

## Round-2 Findings → Fixes (2026-07-09 rerun)

The rerun proved fixes 1–7 worked (kill_stat gated honestly, EQUIP_ALL
clean, clauses covered, ids valid) and exposed three deeper faults that
had been masked by round 1's fictional victories:

| # | Finding | Fix | Where |
|---|---------|-----|-------|
| 8 | Bots stranded on the nether bedrock roof (4/5 at Y=129) — `patrol()` and mob-wave placement used the MOTION_BLOCKING heightmap, which in ceiling dimensions returns the roof top; dimension teleports trusted the given Y blindly. Nothing spawns there; every COMBAT sweep found empty air | `BotPlayer.safeGroundY()`: in `hasCeiling` dimensions, scan downward from below the ceiling for a 2-air pocket over solid non-lava ground. Used by `patrol()`, `spawnHostileMobs()`, and `teleportToDimension()` | `BotPlayer`, `CombatBehavior` |
| 9 | Replan criteria laundering — after kill_stat failed a subtask 3×, L3's replacement subtasks reworded criteria into verifier-dodging synonyms ("dispatched 200 hostile entities", "accumulated 200 enemy eliminations") or dropped the kill clause; the L3-fallback judge passed them and all 5 plans finalized "complete" at 0 kills | Replans may change the approach, never the criterion: `_replan` carries the original criterion through verbatim. Kill patterns also widened (eliminate/dispatch/vanquish verbs; eliminations/foes nouns) as defense in depth | `plan_orchestrator._replan`, `criteria_eval._KILLS_PATTERNS` |
| 10 | Specific-target COMBAT could never fight — (a) fake players trigger no natural mob spawning (user-confirmed), and the wave-spawner only ran in `hostileOnly` mode, so target-specific sweeps starved; (b) namespaced targets (`minecraft:zombified_piglin`) never substring-matched `toShortString()`, so even present mobs were invisible | Wave-spawning now runs for specific targets too and spawns the requested type (`EntityType.byString`); target matching strips the namespace before comparing. Wave rate raised (6 mobs / 5 s cooldown) so kill-count tests complete in bounded time | `CombatBehavior` |
| 11 | Pseudo-target starvation (round 3, Scout: 0 kills amid 69 spawned mobs, honest plan failure) — L3 emitted `target: "hostile_entity"`, which resolves to no entity type; the spawner fell back to generic hostiles while the matcher kept filtering for the pseudo-name and matched nothing | If the directive's target does not resolve via `EntityType.byString`, COMBAT logs it and degrades to a hostile-only sweep, so matcher and spawner always agree | `CombatBehavior.start` |

## Build-Task Findings → Fixes (2026-07-09 stronghold war-game)

A fuzzy build order ("stronghold, ~21 square, walls 8 high, local
materials, near (0,60,0)") produced excellent plans — full clause
coverage, machine-checkable criteria, correct geometry — and zero
fortress. Three faults:

| # | Finding | Fix | Where |
|---|---------|-----|-------|
| 12 | BUILD contract mismatch — L3 puts the shape in `extra.shape` (as our own EXEC reference documented); the mod reads the blueprint from `target` and used the bot's position as origin, ignoring directive x/y/z. Every wall/gate/tower became a default shelter at the bot's feet | Mod: blueprint from `target` with `extra.shape` fallback, alias map for invented shapes (pillar→tower, gate/door→wall, cube/keep→shelter), parametric wall/tower/platform sizes, directive x/y/z honored as build origin (bot teleports adjacent). Agent + l2-mcp: `extra.shape`→`target` normalization with the same aliases. EXEC prompt: BUILD row documents the real contract and the closed blueprint list | `BuildBehavior`, `plan_orchestrator._repair_directive`, `l2-mcp renderers`, `l3_planner` |
| 13 | Criteria evaluator never checked the world — strategy 1 queried `/inventory?bot=`, `/position?bot=`, `/block` (all 404; real paths are `/bot/{name}/...`) and expected the wrong response schema. Every inventory/position/block criterion silently degraded to result-text tokens; two bots "completed" phantom fortresses | `criteria_eval` rewritten onto `api.py` wrappers (correct paths + schema); new mod endpoint `POST /bot/{name}/block_at` for exact block assertions; dimension clauses now also checkable | `criteria_eval`, `api.py`, `HttpApiServer`, `BotPlayer.blockAt` |
| 14 | Compound criteria judged by first clause only — "inventory has 64 netherrack AND 32 basalt AND 16 blackstone" passed on the last directive's success token while netherrack was 0 (basalt-deltas biome has none) | Strategy 1 splits on AND/&&, evaluates every clause; any checkable clause failing ⇒ fail with that reason; all checkable and passing ⇒ pass; otherwise abstain to later strategies | `criteria_eval._strategy_world_state` |

### Stronghold round 2 (post-B-fix rerun): findings 15–17

The rerun failed honestly at the quarry phase — the fixed evaluator
worked perfectly and exposed the next layer: every bot entered the task
with an inventory stuffed by 200+ kills of war loot.

| # | Finding | Fix | Where |
|---|---------|-----|-------|
| 15 | MINE ensure-ownership semantics deadlock — L3 computes incremental counts ("have 64, mine 36 more") but MINE's pre-check ("already have 36") exited instantly; bots pinned at 64/100 forever | MINE count=N now always means "mine N more"; owned count logged instead of short-circuiting | `MineBehavior` |
| 16 | Channel-into-full-inventory silently discarded items — `Inventory.add` leftovers evaporated while `totalMined` counted them as delivered ("channeled 64, received 0, SUCCESS") | Overflow dropped at the bot's feet and reported; zero-delivered channels FAIL with "inventory full — drop junk first" | `MineBehavior.tickChanneling` |
| 17 | L3 blind to inventory — the world-state summary read the wrong schema (`items`/`id`), so the `inv=` section was always empty and no plan could know space was exhausted | Summary fixed to real schema, plus `inv_slots=N/36` with an explicit FULL warning; new DROP directive (agent-side intercept over the existing DropAction) documented in the EXEC reference so L3 can shed junk | `agent._l3_orchestrator_world_state`, `agent._l3_orchestrator_dispatch`, `l3_planner`, `l2-mcp KNOWN_KINDS` |

### Stronghold round 3 (post-C-fix rerun): findings 18–20

Round 3 built real fortress architecture at the ordered coordinates —
walls, towers, gate platforms, all world-verified — and still finalized
0/5 complete. The remaining failures were all criteria-shaped:

| # | Finding | Fix | Where |
|---|---------|-----|-------|
| 18 | PLAN-time criteria hallucinate geometry — gate check inside a lava lake at y=15, wall check at y=78 above a y=60 build, clear-space check at y=-43 (below the world, `void_air` forever). Real construction failed imaginary checks | (a) Plan-time geometry validation: every block-at criterion coordinate probed via `block_at`; `void_air` ⇒ plan rejected and re-planned once with the violation named. (b) EXEC-time criteria grounding: when a subtask's directives include BUILDs with explicit origins, its block-at criterion is REPLACED by exact derived checks ("block at (origin) is (material)") — deterministic translation from the plan's own build orders, not an LLM rewrite. (c) PLAN prompt geometry rules (world y-ranges; criteria must sit inside the built volume) | `plan_orchestrator._validate_criteria_geometry` / `_derive_build_criteria`, `l3_planner._PLAN_SYSTEM_PROMPT` |
| 19 | Criteria immutability pinned bots to malformed originals — Mystic's legitimate y78→y60 self-correction was blocked; Scout died on an unreachable void check | Evidence-gated replacement: a replan may change the criterion IFF the original is PROVABLY impossible (targets `void_air`) and the replacement is not. Everything else still carries through verbatim | `plan_orchestrator._replan`, `_criterion_impossible` |
| 20 | Directive-identity race — `set_directive` is async (enqueued to the server thread); the poller's first read could see the PREVIOUS directive's COMPLETED status (phantom instant MINE successes, Tiller's basalt famine), and the post-completion cleanup cancel could kill the NEXT directive on another HTTP pool thread (`cancelDirective — active=MINE`) | Directives carry a monotonically increasing `id` (returned by set, present in `/brain`); the poller pins to its own id — older id ⇒ "not started yet", newer ⇒ "superseded"; cancels are id-scoped and the mod ignores a cancel for a non-active id | `Directive`, `BotBrain.cancelDirective(long)`, `HttpApiServer`, `agent._poll_directive`, `api.cancel_directive` |

### Round-3 field inspection: finding 21

| # | Finding | Fix | Where |
|---|---------|-----|-------|
| 21 | Terrain-camouflaged construction — the round-3 walls were netherrack in a netherrack cave: invisible to the player standing on them (user-confirmed in-world) and unfalsifiable to block checks (natural terrain auto-passes a netherrack criterion; only the wall's 21-block continuity and one oak-planks patch proved placement). Walls were also embedded in solid rock rather than open space | (a) Standing rule (user directive): strongholds are built from `minecraft:quartz_block` ONLY — visually and verifiably distinct from all terrain. (b) New `clear` BUILD blueprint excavates a size×height×size pocket (16 blocks/tick, bedrock-safe, no drops) so structures stand in open space; plans MUST clear before building; excavation verified by "block at pocket-center is air" derived criterion | `BuildBehavior` (clear mode), `l3_planner` prompts, `plan_orchestrator._derive_build_criteria`, aliases in agent + l2-mcp |

Deferred: replan criteria immutability for *possible-but-wrong* criteria
(Mystic's y=78 was reachable by building up — and he tried). Full-plan
replan with world evidence remains the future path for those.

## Non-Goals

- No new decision-making in L2 (translation-layer purity holds).
- No mod-side kill attribution beyond vanilla stats (per-mob-type kill
  deltas deferred).
- Hive-mod mirrors deferred until aiplayermod findings settle (per
  direction: test only with aiplayermod).

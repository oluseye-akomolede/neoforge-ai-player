# v3 War-Test Fixes — Tasks

## Mod (aiplayermod)
- [x] `BotPlayer.getStatus()` reports `mob_kills` / `deaths` from vanilla Stats (-1 sentinel on error)
- [x] Build + push JAR to MinIO test+prod (final: md5 fafaeb7af2c18e2408390aab3d17bc8f)
- [x] Verify `/bot status` serves `mob_kills` on the test server (fake-player kills confirmed incrementing)
- [x] Round 2/3: `safeGroundY` ceiling-dimension placement (teleport, patrol, wave spawn)
- [x] Round 2/3: wave-spawning for specific targets; namespace-stripped matching; pseudo-target degrade to hostile-only

## Agent
- [x] `Plan.meta` dict in plan_schema (to_dict/from_dict round-trip)
- [x] Orchestrator snapshots `kills_at_start` into plan.meta at plan creation
- [x] `criteria_eval._strategy_kills` — delta-vs-baseline kill verification, conservative fail without baseline
- [x] `_MOB_SYNONYMS` + `EQUIP`→`EQUIP_ALL` alias + kind uppercasing in `_repair_directive`
- [x] `EQUIP`/`EQUIP_ALL` dispatch intercept → mod bulk-equip endpoint
- [x] PLAN prompt: checkable criteria forms + cover-every-clause rule
- [x] EXEC prompt: `EQUIP_ALL` in directive param reference
- [x] Annotated dimension list (`_dim_lines`) in both prompts
- [x] Agent logging config (INFO, urllib3/httpx→WARNING)
- [x] Rebuild + push agent image, restart aibot-agent-test
- [x] Round 2/3: replan criteria carry-through (verified live — rejected rewrite logged)
- [x] Round 2/3: widened kill patterns (12/12 pattern tests pass)

## l2-mcp
- [x] `MOB_SYNONYMS`, `KNOWN_KINDS`, `KIND_ALIASES` tables in renderers
- [x] `normalize_directive`: alias resolution, `unknown_kind` flag, COMBAT target canonicalization
- [x] Rebuild + push l2-mcp image, rollout (EQUIP alias + mob synonyms verified live)

## Verification
- [x] Rerun the identical war-test command against all 5 bots (rounds 2 and 3)
- [x] Kill criteria evaluated via `kill_stat` strategy (visible in agent logs)
- [x] Forge's equip step succeeds via EQUIP_ALL
- [x] No plan stages in `ae2:spatial_storage` or other special-purpose dims
- [x] All 5 bots complete "killed 200 enemies" against verified kill deltas
      (Axiom 209, Forge 214, Mystic 206, Tiller 222, Scout 260; 0 deaths)
- [x] Comparison report delivered

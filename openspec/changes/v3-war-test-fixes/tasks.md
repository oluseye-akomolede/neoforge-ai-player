# v3 War-Test Fixes — Tasks

## Mod (aiplayermod)
- [x] `BotPlayer.getStatus()` reports `mob_kills` / `deaths` from vanilla Stats (-1 sentinel on error)
- [x] Build + push JAR (md5 d28506f3bcbb177339d58a2b40c04c0f) to MinIO test+prod
- [ ] Verify `/bot status` serves `mob_kills` on the test server

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
- [ ] Rebuild + push agent image, restart aibot-agent-test

## l2-mcp
- [x] `MOB_SYNONYMS`, `KNOWN_KINDS`, `KIND_ALIASES` tables in renderers
- [x] `normalize_directive`: alias resolution, `unknown_kind` flag, COMBAT target canonicalization
- [ ] Rebuild + push l2-mcp image, rollout

## Verification
- [ ] Rerun the identical war-test command against all 5 bots
- [ ] Kill criteria evaluated via `kill_stat` strategy (visible in agent logs)
- [ ] Forge's equip step succeeds via EQUIP_ALL
- [ ] No plan stages in `ae2:spatial_storage` or other special-purpose dims
- [ ] Comparison report delivered

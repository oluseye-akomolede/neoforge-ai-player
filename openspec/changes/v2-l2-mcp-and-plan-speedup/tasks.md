# v2 Tasks

## Speedups (this change)
- [x] llm-gateway: `format` field on ChatRequest + shim, forwarded to Ollama
- [x] llm-gateway: `keep_alive` (env L3_KEEP_ALIVE, default 24h) on every Ollama call
- [x] agent/l3_planner: `format:"json"` on PLAN / EXEC / REPLAN payloads
- [x] agent/l3_planner: `_compact_plan` / `_compact_subtask` prompt compaction
- [x] agent/fast_planner.py: deterministic patterns (mine/craft/smelt/channel/farm/goto/teleport)
- [x] agent/plan_orchestrator: Phase-0 fast path + pre-baked directive dispatch (skip EXEC when `subtask.directives` pre-populated and attempts == 0)
- [x] Unit test: 9 pattern cases incl. fall-throughs
- [ ] Measure: log-derived before/after latency for a fast-path vs L3-path command

## L2 MCP (follow-up change, spec: l2-mcp-translation-layer)
- [x] Scaffold `l2-mcp` service (FastAPI + MCP tool registry), Phase A renderers only
- [x] Extract `_repair_directive`, dimension aliases, item normalization into l2-mcp with in-process bypass copies retained
- [x] Diff narration renderer (world snapshot delta)
- [x] Error humanization table (known L1 failure strings → cause lines)
- [x] Agent: L2_MCP_URL wiring with fail-open bypass
- [ ] Phase B (blocked on hardware/CPU decision): L2_MODEL on CPU-Ollama or RTX 3050; persona/voice + result verbalization renders
- [x] Manifests: l2-mcp deployment + service (minecraft-test first)

## Plan-template memory (follow-up)
- [x] Normalize task text (numbers → N, item names canonical) and store with archived plans
- [x] On new task: exact-normalized match against successful archives → clone plan, reset statuses, re-substitute count
- [ ] pgvector similarity variant behind a confidence threshold

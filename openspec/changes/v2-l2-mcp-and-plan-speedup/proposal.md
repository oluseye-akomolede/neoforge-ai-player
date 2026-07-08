# v2: L2 MCP Translation Layer + Plan-Generation Speedup

## Why
Architecture review findings (2026-06):

1. **Every plan pays full L3 latency even for trivial commands.** "mine 16 iron ore" costs a 15-45s PLAN call + an EXEC call per subtask, all on a single GPU serialized behind MAX_INFLIGHT=1.
2. **The gateway shim silently dropped `format`** — brain.think() and l3_planner sent `format:"json"` and it never reached Ollama, degrading JSON reliability for every routed call since the gateway cutover. Malformed JSON → parse fail → full-cost retry.
3. **No `keep_alive`** — Ollama's 5-minute default unloads the 14B after idle; the next call pays a multi-second cold load.
4. **Exec-prompt bloat** — every EXEC/REPLAN call re-embedded the full plan JSON including all previously-emitted directives (agent) / unbounded drone_reports (hive). Input tokens grow with plan age.
5. **L2 logic is scattered and imperative** — repair shims, alias maps, and item normalization live as ad-hoc code in two codebases with no ownership boundary; L1's vocabulary drifts from L3's.

## What changes

### Implemented in this change (speedups; no new hardware)
- **Deterministic fast-path planner** (`agent/fast_planner.py`): anchored patterns for mine/craft/smelt/channel/farm N item, goto x y z, teleport to <dim> produce a complete Plan with pre-baked directives. `plan_orchestrator._step` dispatches pre-baked directives without an EXEC call. Result: common commands run with **zero LLM calls** (criteria checks were already deterministic). Retries fall through to L3, so a wrong fast-path guess self-heals.
- **Gateway `format` passthrough** (native + shim) — fixes the dropped-format regression; Ollama now grammar-constrains JSON output at the sampler.
- **Gateway `keep_alive`** (default `24h`, env `L3_KEEP_ALIVE`) — pins the 14B in VRAM.
- **Prompt compaction** — EXEC/REPLAN prompts embed a plan *outline* (id/status/description per subtask) instead of full state; current-subtask history capped.
- `format:"json"` on all agent planner calls.

### Spec'd, not yet implemented (see l3-spec-driven-planning + l2-mcp-translation-layer)
- **l2-mcp service** — Phase A deterministic translation (absorbs `_repair_directive`, alias maps, item normalization); Phase B small-model rendering on CPU or the incoming RTX 3050. Never the L3 GPU.
- **Plan-template memory** — reuse archived successful plans for near-identical tasks (pgvector similarity on normalized task text), reset statuses, re-substitute counts. Falls back to L3 on any mismatch.
- **Static-prefix prompt layout** — restructure system prompts so the per-caller-class prefix is byte-identical across calls, letting Ollama's KV prefix cache skip re-ingesting the directive reference each time.

## Expected impact (current hardware)
| Path | Before | After |
|---|---|---|
| "mine 16 iron ore" | ~30-60s LLM overhead (PLAN+EXEC) | ~0s LLM (fast path) |
| First call after idle | +5-15s model cold load | 0 (keep_alive) |
| Any malformed-JSON retry | full extra L3 call | ~eliminated (grammar-constrained) |
| EXEC call on an aged plan | grows with history | bounded input size |

## Out of scope
- L4 refinement/escalation of plans (user deferred; costs acceptable but holding until L3 GPU upgrade lands)
- Native Ollama `tools` parameter migration (Phase B+ of the MCP spec)

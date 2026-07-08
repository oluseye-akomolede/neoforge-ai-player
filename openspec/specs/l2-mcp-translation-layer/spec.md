# L2 MCP Translation Layer Specification

## Purpose
Restructures L2 from imperative middleware into an MCP server that sits on the L1↔L3 boundary. L2's only job is **translation on the tool boundary**: moving information across the seam, reshaping surface form without altering truth value or making choices.

The hard constraint this design is built around: **the L2 model does zero decision-making, judgment, or correctness-checking.** It is too small to be trusted with any of that. Every L2 function is reversible, checkable, judgment-free language work. Decisions stay at L3 (and L4); ground truth stays at L1.

## Hardware reality (design constraint)

| Phase | L2 backend | Hardware |
|---|---|---|
| **A (now)** | Deterministic template renderers — no model at all | none required |
| **A+ (optional now)** | Small model on **CPU** via Ollama (`num_gpu: 0`) for the render-quality functions. smollm2:1.7b or qwen2.5:1.5b at Q4 — ~10-20 tok/s on CPU is acceptable for short translations | existing node CPU |
| **B (when the spare RTX 3050 8GB is installed)** | qwen2.5:3b (same family as L3, consistent instruction-following) or phi-3-mini on the dedicated 3050 | RTX 3050 8GB |

The L2 model MUST NOT share the L3 GPU. Loading a second model on the L3 device evicts or fragments the 14B's KV cache and turns every L3 call into a partial cold start. CPU or dedicated-GPU only.

## Requirements

### Requirement: MCP Server Identity
A new service `l2-mcp` MUST expose the bot action vocabulary as MCP tools over HTTP. The agent process is the MCP client: it fetches tool schemas, injects them into L3 prompts (or Ollama's native `tools` parameter), and routes L3's tool calls through `l2-mcp` to the mod API (L1).

```
L3 (qwen2.5:14b via llm-gateway)
  ↑ tool schemas + rendered context     ↓ tool calls
L2-MCP (translation layer — templates now, small model later)
  ↑ raw world state                     ↓ validated mod-API calls
L1 (aiplayermod HTTP API :3100)
```

#### Scenario: Tool advertisement
- GIVEN the agent begins a planning or exec call for bot Forge
- WHEN it fetches `tools/list` from l2-mcp
- THEN it receives the directive vocabulary (MINE, CRAFT, GOTO, TELEPORT, …) as MCP tool schemas
- AND the schemas were re-rendered against current world state (see Dynamic Tool Descriptions)

### Requirement: Zero-Decision Boundary
Every l2-mcp function MUST be classifiable as translation. The service MUST NOT:
- choose between candidate actions
- decide whether a subtask is complete (that is criteria_eval's job, using deterministic strategies first)
- suppress, reorder, or re-rank information
- resolve ambiguity (it MAY flag ambiguity for L3 to resolve)

#### Scenario: Ambiguous argument
- GIVEN L3 emits `{"kind":"MINE","target":"ore"}` (ambiguous item)
- WHEN l2-mcp normalizes arguments
- THEN it does NOT pick an ore type
- AND it returns a structured flag: `{"ambiguous":"target","candidates":["iron_ore","gold_ore",...]}` for L3 to re-decide

### Requirement: Translation Functions
The twelve functions, grouped by phase:

**Phase A — deterministic templates (no model):**
| Function | Behavior |
|---|---|
| Argument normalization | Coerce fuzzy L3 calls to schema (`"iron ore"` → `minecraft:iron_ore`, count strings → ints). Flag — never resolve — ambiguity. Absorbs today's `_repair_directive`. |
| Vocabulary stabilization | One canonical term set for L1's inconsistent naming (`raw_beef`/`beef`, dimension aliases). Absorbs today's alias maps. |
| Unit/coordinate translation | `(x,y,z)` deltas → "12 blocks NE"; ticks → "~30 seconds"; durability fractions → "axe nearly broken". |
| Diff narration | Compare consecutive world snapshots, emit only what changed. Template: "+3 zombies within 16 blocks; health 18→14; night fell." |
| Tool-availability surfacing | Filter/re-render the tool list against state (no pickaxe → MINE schema notes "requires tool acquisition first"). |
| Multi-result batching | Stitch several tool returns into one structured summary block. |
| Error humanization | Map known Java stack traces / failure codes to plain cause lines ("pathfinding failed: target unreachable through walls"). Table-driven. |
| World-state → tool-vocabulary transcoding | Render raw L1 JSON into the exact nouns/verbs the tool schemas use. |

**Phase B — model-backed rendering (CPU model or the 3050):**
| Function | Behavior |
|---|---|
| Dynamic tool descriptions | Live-rewrite MCP schema descriptions against current world state in fluent language. |
| Result verbalization | Narrate raw tool returns into L3's planning register. |
| Persona/voice rendering | Same facts, per-bot archetype tone (Forge terse, Mystic ornate). Player-facing chat only — never L3-facing content. |
| Localization | Inbound player text / outbound bot chat in the player's language; L3 stays monolingual. |

#### Scenario: Phase A works with no model configured
- GIVEN `L2_MODEL` is unset
- WHEN any Phase A function is called
- THEN it completes via templates with zero LLM involvement
- AND Phase B functions return the input unchanged (identity fallback) rather than erroring

### Requirement: Fail-Open Degradation
If l2-mcp is down, the agent MUST bypass it: L3 receives raw L1 data and the static directive reference (today's behavior). Translation is an enhancement, never a dependency.

### Requirement: Truth Preservation Property
For every rendering function: any fact extractable from the output MUST be extractable from the input, and no fact in the output may contradict the input. Renderings carry the source payload alongside (`{"rendered": "...", "source": {...}}`) so L3 tooling and the dashboard can always reach ground truth.

### Requirement: Configuration
| Env | Default | Meaning |
|---|---|---|
| `L2_MCP_URL` | unset (bypass) | Agent-side: where to find l2-mcp |
| `L2_MODEL` | unset (templates only) | Ollama model name for Phase B |
| `L2_OLLAMA_URL` | `http://localhost:11434` | MUST point at CPU or the 3050 instance — never the L3 GPU |
| `L2_RENDER_TIMEOUT_MS` | 1500 | Per-render budget; on timeout, fall back to template/identity |

### Requirement: Latency Budget
Phase A functions MUST complete in <10ms. Phase B renders MUST respect `L2_RENDER_TIMEOUT_MS` and fall back to the Phase A/identity path on breach — a slow translation must never add tail latency to an L3 round-trip.

## Migration path
1. Extract existing translation logic (`_repair_directive`, dimension aliases, item normalization from fast_planner) into the l2-mcp Phase A service. Agent keeps in-process copies as the bypass path.
2. Switch `l3_planner.call_exec` to build its world-state / directive-reference sections from l2-mcp renders.
3. (Hardware lands) enable Phase B model; move persona/voice + result verbalization behind it.
4. (Later) native Ollama `tools` parameter with l2-mcp schemas instead of the prompt-embedded DIRECTIVE PARAM REFERENCE.

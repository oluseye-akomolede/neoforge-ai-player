# v12 design — Retire the behavioral replay memory

## Context: the two "replay past success" systems

| System | Storage | Match | Feeds | Live where |
|---|---|---|---|---|
| `semantic_memory` (vector RAG) | pgvector `memories` | embedding similarity | legacy `planner.orchestrate`/`decompose` (no skills) | **prod** (L3 flag unset) |
| `plan_memory` (template replay) | disk archive (`plan_store.ARCHIVE`) | exact normalized text | new L3 plan layer (`plan_orchestrator`) | test (L3 flag set) |

Both are reachable; the vector RAG is the one the request names. The write
side of the vector RAG is `_store_plan_outcome` (`agent.py:1236`), which
embeds the raw directive steps. Its read side is `recall_for_prompt`
(`agent.py:526`) → `memory_context` → `"## Relevant memories"` in
`planner.py`.

## Decisions

### 1. Delete `_store_plan_outcome`; do not stub it

The function's only side effect is the semantic write; its 7 call sites exist
solely to record a plan terminal state for that write. Stubbing it to a no-op
leaves dead-looking code; deleting it is the honest streamline. Plan
persistence is *not* affected — `_shadow_plan_write` / `_shadow_plan_finalize`
(`agent.py:1186/1220`) already archive to `plan_store`, and v11's
`trajectory_log` captures the L3 calls independently.

- **Why keep the world-state writes**: `_store_success_memory` records
  *where* ore is and *what* was crafted; `_learn_from_error` records *what
  failed*. Those feed `recall_for_prompt` as facts the planner can use, not as
  demonstrations of how to decompose. They stay.

### 2. `plan_memory` reuse is skill-only

`_reusable` gains one predicate: **every directive in every subtask must be
`kind == "SKILL"`** (case-insensitive). Rationale:

- A `SKILL` directive is deterministic, self-verifying, and parameterized —
  replaying "run `mine_and_smelt`" is safe and is exactly what skills-first
  wants.
- A raw-directive plan (`MINE`, `SMELT`, …) is the old hand-decomposition; if
  it's allowed to replay, the skill path is bypassed with pre-baked directives,
  which is the regression this change prevents.
- Because `_build_index()` and `record()` both call `_reusable`, the gate
  applies to both the lazily-built index and live recording. The existing
  archive's raw-directive plans simply stop being indexed/reused; nothing is
  deleted.

### 3. Count substitution reaches `extra`

Skill parameters live in `extra` (`{"kind":"SKILL","target":"mine_and_smelt",
"extra":{"target":"iron_ore","count":16}}`), not the top-level `count` field.
`_substitute_count` currently only rewrites `directives[].count`, so a replayed
skill would silently keep the template's old count. Extend it to rewrite any
`extra` value equal to the old count (covers `count` and any other numeric
param).

### 4. Prod `OLLAMA_URL`

The prod `agent-config` secret points at `ollama.mindcraft` (dead since the
ollama migration). The live L3 service is `ollama-l3` in `minecraft-test`; the
prod agent already reaches `pgvector.minecraft-test` cross-namespace, so
repointing to `http://ollama-l3.minecraft-test.svc.cluster.local:11434` is
consistent. (The gateway `llm-gateway.minecraft-test` is test-only per
`hive-system.yaml`, so we point at ollama directly, matching the old pattern.)

## Risks / trade-offs

- **Loss of "what worked" recall** → intentional. It is the behavioral signal
  RL replaces; keeping it would fight DPO/GRPO.
- **Skill-only replay has a smaller hit-rate** → correct: fewer, safer replays.
  Non-skill plans now always cost one fresh L3 plan, which is the point
  (directives are the fallback, not the cache).
- **Count substitution is best-effort** → it still only fires when both tasks
  carry exactly one number (unchanged); the `extra` walk is a strict widening.

# v12 — Retire the behavioral "replay past success" memory

## Why

There are two systems that inject *previous successful attempts* back into the
planner, and both encode the exact behavior this design is trying to remove —
**directives as the first shot**:

1. **Vector RAG** (`semantic_memory.py`, pgvector). `_store_plan_outcome`
   (`agent.py`) writes `"Plan succeeded: <task>. Steps that worked: MINE ->
   SMELT"` into the `memories` table on every plan completion, and
   `recall_for_prompt` (`agent.py:526`) feeds the top-6 similar memories back
   into the legacy planner prompt as
   `"## Relevant memories … use these to make better plans."` The exemplars are
   raw directive sequences — the pre-skill behavior.
2. **Template replay** (`plan_memory.py`, disk archive). On an exact
   normalized-text match it clones a past successful plan, **including its raw
   `directives`**, and runs it with **zero L3 calls**. A raw-directive archive
   keeps "directives first" alive even in the skill-aware L3 plan layer.

Both fight the skill-first design and both fight v11's RL: DPO/GRPO are trying
to move the weights toward skills-first, while these systems keep re-injecting
directive-first demonstrations into the prompt (RAG) or bypass the model
entirely with pre-baked directives (replay). The design principle is
**skills first, directives as fallback** — and both systems hard-code the
fallback as the primary.

## What

- **Retire the behavioral write.** Delete `_store_plan_outcome` and its call
  sites. Plan persistence is unaffected (`_shadow_plan_finalize` →
  `plan_store.archive` stays); what goes away is only the *semantic vector*
  record of "the directive steps that worked."
- **Keep the world-state memory.** `_store_success_memory` (where ore /
  crafted items are), `_learn_from_error` (avoiding mistakes), and
  `_inject_knowledge` / `_set_work_area` (player facts) stay — they encode
  *what/where*, not *how to decompose*.
- **Gate `plan_memory` to skill-only replay.** A plan is reusable only if every
  directive is `kind: SKILL` (deterministic, self-verifying, safe to replay
  verbatim). Raw-directive plans fall through to a fresh L3 plan. Fix count
  substitution to reach `extra` (where skill params live) so a replayed skill
  isn't silently re-run at the template's old count.
- **Fix prod `OLLAMA_URL`** (stale `ollama.mindcraft`, dead) — found while
  tracing the planner; repoint to the live L3 service.

## Non-goals

- No change to the two-path architecture or the `USE_L3_PLAN_LAYER` flag —
  unifying to a single skill-aware path is a larger, separate change (and prod
  stays on the legacy path until we're confident, per `agent.yaml`).
- No removal of the *world-state* memory systems (location/event/error/
  knowledge) — those remain useful under RL.
- No change to RL capture (R1/R2 trajectory + reward) — this is the cleanup
  that makes RL's training signal the *only* behavioral signal.

## Related

- **v10** introduced the skill layer these memories predate and contradict.
- **v11** (RL) is the replacement for the behavioral memory — weights-learned
  skills-first beats few-shot exemplars (no stale-demo drift, no prompt tax).
- [[l3-skill-emission-gap]] documents why the skill path was never actually
  exercised in the prior test (test harness ran the legacy planner).

## Sequencing

Single pass, agent-side only (no mod change). Retire the write → gate replay →
fix the URL → verify (`py_compile` + a `plan_memory` unit check + YAML lint).

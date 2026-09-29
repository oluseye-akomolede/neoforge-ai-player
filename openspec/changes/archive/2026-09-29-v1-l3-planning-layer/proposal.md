# v1 L3 Planning Layer

## Why
Currently `planner.decompose` and `planner.orchestrate` are single-shot: one L3 call returns a directive that L1 executes, with retries living in the BehaviorState classes. There's no persisted plan, no first-class subtask retry semantics, and no per-bot view of what the bot is currently working on or what's left.

The new spec (`l3-spec-driven-planning`) introduces a two-phase pattern:
- **Phase 1** generates a structured plan once per task
- **Phase 2** generates a directive (or set of directives) for the current subtask each loop iteration
- L2 (the agent) owns plan state on disk

This makes bot reasoning deliberate, makes retries first-class, and gives the dashboard a real view of what every bot is currently thinking about.

## What changes

Spec domains touched:
- **l3-spec-driven-planning** — new spec (just added)
- **bot-brain** — extended: brain now consumes plans, not just one-shot directives
- **bot-coordination** — extended: multi-bot orchestration produces a plan per bot, not just a parallel directive set

## Files touched
- `agent/planner.py` — add `plan_task()`, `execute_subtask()`, `replan_subtask()`; keep `decompose` and `orchestrate` as backward-compat thin wrappers that call the new plan-aware paths
- `agent/agent.py` — the bot's main loop now reads/writes the plan file each tick; calls planner.execute_subtask when a current subtask exists
- `agent/plan_store.py` — new module for plan file I/O
- `agent/plan_schema.py` — new module with Plan/Subtask dataclasses + validation
- `agent/criteria_eval.py` — new module for the three-strategy evaluator
- `agent/api.py` — three new endpoints serving `agent_plans/*.json`

## Cross-repo coordination
- **manifests**: add Longhorn PVC for `agent_plans/` (or fold into the existing agent PVC at `/opt/aibot-agent/data/agent_plans`)
- **aibot-dashboard**: new "Current Plan" panel per bot showing subtask list + progress

## Out of scope for v1
- Cross-bot plan dependencies (Forge's plan referencing Tiller's plan) — v2
- Plan compaction (if a plan grows huge, summarize older subtasks) — v2

## Not verified at archive

Added 2026-09-29, when this change was reticked against `main`
(`dd88be0`, which is also the prod image `agent:qwen3coder-dd88be0`). The
feature is live — `agent/l3_planner.py` and `plan_orchestrator.py` landed on
main in `2dc6a91` — but four items in the original `tasks.md` do **not** match
what the code does, so those boxes are left unticked and listed here rather than
being reconstructed:

1. **`planner.plan_task` / `planner.execute_subtask`.** The plan-aware calls
   exist, but as `l3_planner.call_plan` / `call_exec`, not as functions of those
   names in `planner.py`.
2. **`decompose` / `orchestrate` as plan-aware thin shims.** Not true: they
   remain the older single-shot entry points in `agent/planner.py` and
   `agent/openai_brain.py`, unwired to the plan layer.
3. **Criteria "L3 fallback at priority=4".** The fallback call exists
   (`_strategy_l3_fallback`); the `priority=4` label is nowhere in the code. The
   code also runs a `kill_stat` strategy between world-state and result-text
   that the original task sheet does not mention.
4. **Replan "reset attempts, status=pending".** The in-place splice at the same
   `id` exists (`plan_orchestrator.py:1078`), but the reset does not: `_replan`
   increments a `replans` counter bounded by `MAX_REPLANS_PER_SUBTASK`
   (line 1042) and does not reset `attempts` to 0.

The Phase A round-trip test, the Phase H infra paths, the Phase G dashboard
exercise, and the end-to-end acceptance test are environment/UI observations and
are likewise not verifiable from the tree. Full per-task evidence is in
`tasks.md`.

The spec delta in this change describes the behaviour live on `dd88be0` — i.e.
**before** v15. Where v15 changes the entry/exit contract (chat vs order, stop,
clarify/refuse, honest finalize, `cancelled`), v15's own delta covers it and is
deliberately not duplicated here.

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

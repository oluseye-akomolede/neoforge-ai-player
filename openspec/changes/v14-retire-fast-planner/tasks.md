# v14 tasks — Retire the deterministic fast-planner shim

Agent-side only; no mod change.

- [x] **Delete `agent/fast_planner.py`** — the whole module (`try_plan`, the
      gather/goto/teleport regexes, the plural tables).
- [x] **Remove the Phase-0 call** — `plan_orchestrator.execute_task`: drop
      `import fast_planner` and the `plan = fast_planner.try_plan(...)` block;
      `plan_memory.lookup` becomes the first planning phase.
- [x] **Refresh stale comments** — `_step`'s "pre-baked directives
      (fast_planner)" → plan-memory replay; the `trajectory_log` comment's
      "pre-baked fast-path subtasks" → "plan-memory replay subtasks".
- [x] **Proof — headless** — `python3 -m py_compile plan_orchestrator.py
      plan_memory.py` (PY_COMPILE_OK); `grep -rn fast_planner agent/` returns
      nothing (no dangling refs); `plan_memory.lookup` still reachable.
- [x] **Deploy + retest** — rebuild/push `aiplayermod/agent:latest`; rerun
      `l3_emits_skill` (expect: no `fast-path MINE`, no bogus `CHANNEL
      iron_ore_blocks`, L3 emits `SKILL mine_and_smelt`, pass 1/1).

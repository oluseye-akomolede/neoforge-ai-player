# v14 — Retire the deterministic fast-planner shim

## Why

`fast_planner.py` is a Phase-0 shim that recognizes a narrow set of
whole-command shapes ("mine 16 iron ore", "goto x y z", "teleport to the
nether") and builds a `Plan` with pre-baked raw directives, skipping L3
entirely. It was written to cut ~15-45s of plan latency when L3 ran on two
RTX 3050s.

That rationale is gone and the shim now actively fights the skills-first
design:

1. **L3 moved to a V100 NVLink pair** (60.7 tok/s) — planning is seconds, not
   tens of seconds, so the latency win is negligible.
2. **Greedy gather patterns mangle compound commands.** `mine\s+(\d+)\s+(.+?)$`
   matches "mine 8 iron ore blocks, then smelt them into iron ingots" as a
   single `MINE` of
   `minecraft:iron_ore_blocks,_then_smelt_them_into_iron_ingot` — the exact
   `CHANNEL iron_ore_blocks → Unknown item ID` / `MINE …_then_smelt_…` noise in
   the v13 test run. L3 would have emitted `SKILL mine_and_smelt`; the fast
   path intercepts it first.
3. **Ore→raw criteria mismatch.** "mine 16 iron ore" bakes
   `inventory has 16 minecraft:iron_ore`, but 1.21 mining drops `raw_iron` and
   `ITEM_SYNONYMS` no longer maps `iron_ore→raw_iron` (af17ebf), so the
   criterion can never match and the fast path self-heals through L3 after a
   wasted MINE+channel cycle.
4. **It is the last directives-first path.** v12 removed the behavioral replay
   memory for the same reason; v13 added skill-output grounding on the L3 side.
   The fast path is the one remaining component that emits raw directives
   before L3 gets a chance to select a skill.

## What

- **Delete `fast_planner.py`** — `try_plan`, the gather/goto/teleport regexes,
  and the plural/irregular-word tables.
- **Remove the Phase-0 call** in `plan_orchestrator.execute_task` and the
  `import fast_planner`.
- **Keep** `plan_memory` (Phase 0.5) and the `_step` pre-baked-dispatch branch:
  `subtask.directives` is also populated by plan-memory's SKILL-only replay
  (v12), so that field and the attempt-0 skip are **not** fast-planner
  specific and stay.

## Non-goals

- No change to `plan_memory` (its SKILL-only replay is the intended "0 LLM
  call" path for repeat tasks).
- No change to the L3 planning/exec path, criteria evaluation, or the v13
  grounding.
- No change to the `Subtask.directives` schema or the plan-store/archive
  format.

## Related

- **v12** retired the behavioral replay memory for the same reason — a
  directives-first path that predates and contradicts skills-first.
- **v13** added skill-output grounding, which the fast path bypasses.
- **[[project-l2-hardware-and-testing]]** records the L3 V100 move that
  obsoleted the latency rationale.

## Sequencing

Agent-side only, no mod change. Delete the module → remove the Phase-0 call →
refresh the two stale comments → `py_compile` + grep for dangling refs →
rebuild/push the agent image → rerun `l3_emits_skill` (expect the fast-path
`CHANNEL iron_ore_blocks` / `MINE …_then_smelt…` lines to be **gone**, and L3
to emit `SKILL mine_and_smelt` on attempt 1).

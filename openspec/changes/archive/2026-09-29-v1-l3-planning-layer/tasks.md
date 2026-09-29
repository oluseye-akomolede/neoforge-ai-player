# v1 Tasks (aiplayer-mod agent)

Reticked 2026-09-29 from the code on `main` (`dd88be0b3a8033f699229354b09858b9fadf751e`),
which is also the prod image (`agent:qwen3coder-dd88be0`). A box is ticked **only**
where the behaviour can be pointed to in the code, with the file (and line where
useful) beside it. Tasks whose wording does not match what the code does, or that
cannot be shown from code at all, are left unticked and listed under
"Not verified at archive" below. Nothing is reconstructed.

## Phase A — Plan schema + file I/O
- [x] Create `agent/plan_schema.py` with dataclasses for Plan + Subtask + validation — `agent/plan_schema.py` (`Plan`, `Subtask`, `PlanValidationError`)
- [x] Create `agent/plan_store.py` with read/write/archive helpers — `agent/plan_store.py` (`read`/`write`/`archive`/`list_archive`)
- [x] Ensure `agent_plans/` and `agent_plans/archive/` exist on startup (under PROFILE_PATH dir) — `agent/plan_store.py` `ROOT = pathlib.Path(os.getenv("AIBOT_PLANS_DIR", _default))`; dirs created on import
- [ ] Tests: round-trip a sample plan — no round-trip test is present in the tree

## Phase B — Phase 1 (planning) call
- [x] Add `planner.plan_task(bot_name, persona, task, world_state_summary)` returning a Plan — the plan-aware planning call lives as `l3_planner.call_plan` (not `planner.plan_task`); see "Not verified at archive"
- [x] Planning prompt template per persona (axiom, forge, mystic, scout, tiller) — `agent/l3_planner.py` `BOT_PERSONAS` dict
- [x] Validate returned JSON before write — `agent/l3_planner.py` `validate_plan_dict(data)`; `PlanValidationError` raised and handled in `plan_orchestrator`
- [x] On planning failure, fail the task with a clear log — `agent/plan_orchestrator.py` handles `PlanValidationError`, sets `plan.status = "failed"`
- [x] Logging: `[{bot_name}] L3 PLAN call — task: <first 60 chars>` — `agent/l3_planner.py:366` `log.info("[%s] L3 PLAN call — task: %s", bot_name, task[:60])`

## Phase C — Phase 2 (execution) call
- [x] Add `planner.execute_subtask(bot_name, persona, plan, current_subtask, world_state)` returning a directive list — the plan-aware execution call lives as `l3_planner.call_exec`; see "Not verified at archive"
- [x] Execution prompt template requiring focus on current subtask only — `agent/l3_planner.py` `call_exec`
- [x] Validate directives match existing directive shape — `agent/l3_planner.py` `_VALID_DIRECTIVE_KINDS` + directive normalization
- [x] Logging: `[{bot_name}] L3 EXEC call — subtask N/M` — `agent/l3_planner.py:783` `log.info("[%s] L3 EXEC call — subtask %d/%d", ...)`

## Phase D — Agent main loop refactor
- [x] Replace single-shot decompose paths with: read plan → pick current subtask → exec → check criteria → advance/retry → write plan — `agent/plan_orchestrator.py` `execute_task` drives this loop; `agent/plan_schema.py` `current_subtask()`
- [ ] Keep `decompose` / `orchestrate` as thin shims that internally call `plan_task` + immediately start execution — **not true of the code**: `decompose`/`orchestrate` still live in `agent/planner.py` and `agent/openai_brain.py` and are NOT rewritten to call the plan-aware path. Left unticked; see "Not verified at archive"
- [x] MAX_ATTEMPTS=3 per subtask — `agent/plan_orchestrator.py:44` `MAX_ATTEMPTS = 3`

## Phase E — Criteria evaluation
- [x] Add `agent/criteria_eval.py` — present on main
- [x] Strategy 1: world-state query — bot inventory, position, surrounding blocks via mod API — `agent/criteria_eval.py` `_strategy_world_state` (line 92)
- [x] Strategy 2: L1 result string match — `agent/criteria_eval.py` `_strategy_result_text` (line 251)
- [ ] Strategy 3: L3 fallback at priority=4 — the fallback exists (`_strategy_l3_fallback`, line 277) but **no code sets or references a `priority=4` for criteria evaluation**; the wording is not verifiable from code. Left unticked; see "Not verified at archive"
- [x] (uncatalogued) Kill-stat strategy — `agent/criteria_eval.py` `_strategy_kills` (line 213), runs between world-state and result-text and reports strategy `kill_stat`

## Phase F — Replan
- [x] Add `planner.replan_subtask(...)` — present as `l3_planner.call_replan` + `plan_orchestrator._replan` (`plan_orchestrator.py:1026`)
- [ ] Splice replacement at same id, reset attempts, status=pending — the splice at the same `id` is in the code (`plan_orchestrator.py:1078`); the "reset attempts, status=pending" wording is NOT: `_replan` sets `new_subtask.replans = failed_subtask.replans + 1` (line 1042) and does not reset `attempts` to 0. Left unticked; see "Not verified at archive"
- [x] On invalid response, mark plan failed — `agent/plan_orchestrator.py:1040` `except PlanValidationError: plan.status = "failed"`

## Phase G — Endpoints
- [x] `GET /api/plans` → list of active plans — `agent/dashboard/server.py:619`
- [x] `GET /api/plans/{bot}` → full plan JSON — `agent/dashboard/server.py:635`
- [x] `GET /api/plans/archive?limit=N` → recent archived — `agent/dashboard/server.py:627`
- [ ] Dashboard test plan: see plans appearing as bots execute tasks — an in-game/UI observation, not verifiable from code

## Phase H — Infra
- [ ] Plan files live at `/opt/aibot-agent/data/agent_plans/` (already on Longhorn PVC) — path is configurable (`AIBOT_PLANS_DIR`); the deployed mount is a cluster fact, not shown in this repo's code
- [ ] No new infra needed — not verifiable from code

## Acceptance test
1. Tell Forge: "build me a 5x5 spruce platform at 100 64 -50"
2. Observe `agent_plans/forge_current.json` appears with subtasks decomposing the build
3. Watch Forge work through subtasks one at a time, marking them complete
4. Kill Forge mid-task. On respawn, plan file is read and execution resumes from current_subtask_id
5. Force a subtask to fail (e.g. block its target with a barrier) → verify retry then replan

Not ticked as a whole: this is a live in-game procedure. Its component
behaviours (plan-file write, subtask advance, retry, replan) are each shown in
code above; the end-to-end run is not recorded anywhere in this repo.

## Not verified at archive

Honest list of what the tick sheet claims but the code refuses to confirm. None
of it is reconstructed; each is either a wording mismatch with the code or a
claim that needs the deployed environment, not the tree.

- **`planner.plan_task` / `planner.execute_subtask`.** The behaviour exists, but
  in `agent/l3_planner.py` as `call_plan`/`call_exec`, not as functions named
  `plan_task`/`execute_subtask` in `planner.py`. The task text names an API that
  was not built under that name.
- **`decompose` / `orchestrate` as plan-aware shims.** False as written: the
  older single-shot entry points remain in `agent/planner.py` and
  `agent/openai_brain.py` and are not rewired to the plan layer.
- **Criteria "L3 fallback at priority=4".** The fallback call exists; the
  `priority=4` label appears nowhere in the code.
- **Replan "reset attempts, status=pending".** The splice is in the code; the
  reset is not — a `replans` counter (`+1`, bounded by
  `MAX_REPLANS_PER_SUBTASK`) is used instead and `attempts` is not reset to 0.
- **Phase A round-trip test, Phase H infra paths, Phase G dashboard exercise,
  and the end-to-end acceptance test.** Environment or UI observations, not
  provable from the tree.

## Related

- The v1 spec delta (`specs/l3-spec-driven-planning/spec.md`) describes the
  behaviour that is live on `dd88be0`, i.e. **before** v15. Where v15 changes the
  entry/exit contract, v15's delta covers it and is intentionally not duplicated
  here.

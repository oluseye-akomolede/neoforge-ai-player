# v1 Tasks (aiplayer-mod agent)

## Phase A — Plan schema + file I/O
- [ ] Create `agent/plan_schema.py` with dataclasses for Plan + Subtask + validation
- [ ] Create `agent/plan_store.py` with read/write/archive helpers
- [ ] Ensure `agent_plans/` and `agent_plans/archive/` exist on startup (under PROFILE_PATH dir)
- [ ] Tests: round-trip a sample plan

## Phase B — Phase 1 (planning) call
- [ ] Add `planner.plan_task(bot_name, persona, task, world_state_summary)` returning a Plan
- [ ] Planning prompt template per persona (axiom, forge, mystic, scout, tiller)
- [ ] Validate returned JSON before write
- [ ] On planning failure, fail the task with a clear log
- [ ] Logging: `[{bot_name}] L3 PLAN call — task: <first 60 chars>`

## Phase C — Phase 2 (execution) call
- [ ] Add `planner.execute_subtask(bot_name, persona, plan, current_subtask, world_state)` returning a directive list
- [ ] Execution prompt template requiring focus on current subtask only
- [ ] Validate directives match existing directive shape
- [ ] Logging: `[{bot_name}] L3 EXEC call — subtask N/M`

## Phase D — Agent main loop refactor
- [ ] Replace single-shot decompose paths with: read plan → pick current subtask → exec → check criteria → advance/retry → write plan
- [ ] Keep `decompose` / `orchestrate` as thin shims that internally call `plan_task` + immediately start execution
- [ ] MAX_ATTEMPTS=3 per subtask

## Phase E — Criteria evaluation
- [ ] Add `agent/criteria_eval.py`
- [ ] Strategy 1: world-state query — bot inventory, position, surrounding blocks via mod API
- [ ] Strategy 2: L1 result string match
- [ ] Strategy 3: L3 fallback at priority=4

## Phase F — Replan
- [ ] Add `planner.replan_subtask(...)`
- [ ] Splice replacement at same id, reset attempts, status=pending
- [ ] On invalid response, mark plan failed

## Phase G — Endpoints
- [ ] `GET /api/plans` → list of active plans
- [ ] `GET /api/plans/{bot}` → full plan JSON
- [ ] `GET /api/plans/archive?limit=N` → recent archived
- [ ] Dashboard test plan: see plans appearing as bots execute tasks

## Phase H — Infra
- [ ] Plan files live at `/opt/aibot-agent/data/agent_plans/` (already on Longhorn PVC)
- [ ] No new infra needed

## Acceptance test
1. Tell Forge: "build me a 5x5 spruce platform at 100 64 -50"
2. Observe `agent_plans/forge_current.json` appears with subtasks decomposing the build
3. Watch Forge work through subtasks one at a time, marking them complete
4. Kill Forge mid-task. On respawn, plan file is read and execution resumes from current_subtask_id
5. Force a subtask to fail (e.g. block its target with a barrier) → verify retry then replan

"""L2 orchestration for spec-driven planning.

The single public entrypoint is `execute_task(bot_name, model, task, dispatch_fn,
world_state_fn)`. It runs Phase 1 (plan) then loops Phase 2 (exec) per subtask
until the plan completes, fails, or is paused (returns).

This module is intentionally decoupled from agent.py — agent.py decides WHEN
to call execute_task and provides:
  - dispatch_fn(directive_dict) → result_text (executes a directive via L1)
  - world_state_fn() → world_state_summary string

This keeps the orchestration pure: no global state, no threads, no api module
dependencies.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

import l3_planner
import plan_store
from criteria_eval import evaluate as evaluate_criteria
from plan_schema import Plan, PlanValidationError, Subtask

log = logging.getLogger("aibot.orchestrator")

MAX_ATTEMPTS = 3
MAX_REPLANS_PER_SUBTASK = 2

DispatchFn = Callable[[dict[str, Any]], str]
WorldStateFn = Callable[[], str]


def execute_task(
    bot_name: str,
    model: str,
    task: str,
    dispatch_fn: DispatchFn,
    world_state_fn: WorldStateFn | None = None,
) -> Plan:
    """
    Run a full task end-to-end: plan → exec subtasks → return Plan.

    Returns the final Plan with status set to complete or failed. The plan
    file is also archived on disk.
    """
    world_state_fn = world_state_fn or (lambda: "")

    # Phase 1: plan
    try:
        plan = l3_planner.call_plan(model, bot_name, task, world_state_fn())
    except PlanValidationError as e:
        log.warning("[%s] planning failed: %s", bot_name, e)
        # Synthetic failure plan so the caller has something to log
        import datetime
        plan = Plan(
            task=task, bot=bot_name,
            created_at=datetime.datetime.utcnow().isoformat(),
            status="failed",
            subtasks=[],
            current_subtask_id=0,
        )
        plan_store.write(plan)
        plan_store.archive(plan)
        return plan

    plan_store.write(plan)
    log.info("[%s] plan written with %d subtasks", bot_name, len(plan.subtasks))

    # Phase 2: drive subtasks
    while plan.status == "executing":
        subtask = plan.current_subtask()
        if subtask is None or plan.all_complete():
            plan.status = "complete"
            break
        if not _step(plan, subtask, model, dispatch_fn, world_state_fn):
            # _step returns False when the plan needs to abort
            break

    plan_store.write(plan)
    plan_store.archive(plan)
    log.info("[%s] plan finalized: %s", bot_name, plan.status)
    return plan


def _step(plan: Plan, subtask: Subtask, model: str,
          dispatch_fn: DispatchFn, world_state_fn: WorldStateFn) -> bool:
    """Drive one subtask through one attempt. Returns False if the plan must abort."""
    # Phase 2 exec
    try:
        directives = l3_planner.call_exec(
            model=model, plan=plan, subtask=subtask,
            world_state_summary=world_state_fn(),
            previous_error=subtask.error,
        )
    except Exception as e:
        log.warning("[%s] subtask %d exec failed: %s", plan.bot, subtask.id, e)
        subtask.attempts += 1
        subtask.error = f"exec_call_failed: {e}"
        plan_store.write(plan)
        if subtask.attempts >= MAX_ATTEMPTS:
            if not _replan(plan, subtask, model):
                plan.status = "failed"
                return False
        return True

    subtask.status = "executing"
    subtask.directives = list(directives)
    plan_store.write(plan)

    # Dispatch each directive via L1
    last_result = ""
    for d in directives:
        try:
            last_result = dispatch_fn(d)
        except Exception as e:
            last_result = f"DISPATCH_ERROR: {e}"
            log.warning("[%s] dispatch failed for %s: %s", plan.bot, d.get("kind"), e)

    # Evaluate criteria
    satisfied, strategy, reason = evaluate_criteria(
        bot_name=plan.bot,
        subtask=subtask,
        last_result_text=last_result,
        model=model,
    )
    log.info("[%s] subtask %d criteria: %s (%s) — %s",
             plan.bot, subtask.id, satisfied, strategy, reason)

    if satisfied:
        subtask.status = "complete"
        subtask.error = None
        plan.advance()
        plan_store.write(plan)
        return True

    # Failed this attempt
    subtask.status = "failed"
    subtask.attempts += 1
    subtask.error = reason
    plan_store.write(plan)
    if subtask.attempts < MAX_ATTEMPTS:
        # retry
        subtask.status = "pending"
        plan_store.write(plan)
        return True

    return _replan(plan, subtask, model)


def _replan(plan: Plan, failed_subtask: Subtask, model: str) -> bool:
    """Try to replan a failed subtask. Returns False if the plan must abort."""
    if failed_subtask.replans >= MAX_REPLANS_PER_SUBTASK:
        log.warning("[%s] subtask %d exhausted replans (%d), failing plan",
                    plan.bot, failed_subtask.id, failed_subtask.replans)
        plan.status = "failed"
        return False
    try:
        new_subtask = l3_planner.call_replan(model, plan, failed_subtask)
    except PlanValidationError as e:
        log.warning("[%s] replan refused: %s", plan.bot, e)
        plan.status = "failed"
        return False
    new_subtask.replans = failed_subtask.replans + 1
    for i, s in enumerate(plan.subtasks):
        if s.id == failed_subtask.id:
            plan.subtasks[i] = new_subtask
            break
    plan_store.write(plan)
    log.info("[%s] replanned subtask %d (replans=%d)",
             plan.bot, failed_subtask.id, new_subtask.replans)
    return True

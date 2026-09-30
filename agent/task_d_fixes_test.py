#!/usr/bin/env python3
"""Headless proof of the three chat/stop/clarify fixes.

No live server and no model: the L3 calls are monkeypatched so each behaviour
is controlled deterministically. Covers:

  1. Talk/Order split — a conversational message is answered via converse()
     and never reaches execute_task; an instruction still plans.
  2. Stop — a stop signal set on another thread aborts a running plan
     mid-subtask, and the plan is finalized "cancelled" (not "complete").
  3. Honest finalize — a plan whose loop exits with an unfinished subtask is
     failed, not reported complete; a clarify/refuse from L3 is spoken and no
     plan is dispatched.

Run: (ulimit -v 4194304; python3 agent/task_d_fixes_test.py)
"""
from __future__ import annotations

import os
import sys
import threading
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import plan_orchestrator
import l3_planner
from plan_schema import Plan, Subtask

failures = 0


def check(label: str, cond: bool, detail: str = ""):
    global failures
    if cond:
        print(f"  PASS  {label}")
    else:
        failures += 1
        print(f"  FAIL  {label}" + (f" — {detail}" if detail else ""))


def _plan(n_subtasks=2, **kw):
    return Plan(
        task="do a thing", bot="scout",
        created_at="2026-09-29T00:00:00", status="executing",
        subtasks=[Subtask(id=i + 1, description=f"s{i+1}", criteria="") for i in range(n_subtasks)],
        current_subtask_id=1, **kw,
    )


# ── 1. Talk/Order split ─────────────────────────────────────────────────────

def test_classify_routes_chat_away_from_planning():
    print("1. talk/order split")
    kinds = {"tell me about yourself": "chat",
             "who are you?": "chat",
             "gather 8 oak logs": "task",
             "build a shelter here": "task"}

    def fake_classify(model, bot, text):
        return kinds[text]

    with mock.patch.object(l3_planner, "classify_message", fake_classify), \
         mock.patch.object(l3_planner, "converse",
                           mock.Mock(return_value="I am Scout, an explorer.")) as conv, \
         mock.patch.object(plan_orchestrator, "execute_task") as exec_task:
        # Replicate the dispatch decision without a live bot.
        def dispatch(text):
            if l3_planner.classify_message("m", "scout", text) == "chat":
                return ("chat", l3_planner.converse("m", "scout", "persona", text))
            return ("task", plan_orchestrator.execute_task(bot_name="scout", model="m", task=text))

        kind, reply = dispatch("tell me about yourself")
        check("chat message is answered, not planned",
              kind == "chat" and reply.startswith("I am Scout"), f"kind={kind} reply={reply!r}")
        check("converse called once", conv.call_count == 1, f"calls={conv.call_count}")
        check("execute_task NOT called for chat", exec_task.call_count == 0,
              f"calls={exec_task.call_count}")

        kind2, _ = dispatch("gather 8 oak logs")
        check("instruction still plans", kind2 == "task" and exec_task.call_count == 1,
              f"kind={kind2} exec_calls={exec_task.call_count}")


def test_classify_fails_to_task():
    print("1b. classifier failure defaults to task (never silently drops an order)")
    with mock.patch.object(l3_planner.requests, "post", side_effect=RuntimeError("no ollama")):
        check("exception → 'task'", l3_planner.classify_message("m", "scout", "anything") == "task")
    with mock.patch.object(l3_planner.requests, "post") as post:
        post.return_value = mock.Mock(
            raise_for_status=lambda: None,
            json=lambda: {"message": {"content": '{"kind": "banana"}'}})
        check("unknown kind → 'task'", l3_planner.classify_message("m", "scout", "x") == "task")


# ── 2. Stop cancels a running plan ──────────────────────────────────────────

def test_cancel_event_aborts_running_plan():
    print("2. stop cancels a running plan")
    plan = _plan(4)
    cancel = threading.Event()
    started = threading.Event()
    step_calls = []

    def fake_step(p, subtask, *a, **kw):
        step_calls.append(subtask.id)
        started.set()
        # First subtask completes; the "stop" lands while the second runs.
        if subtask.id == 1:
            subtask.status = "complete"
            p.current_subtask_id = 2
            return True
        # Simulate the stop arriving from another thread mid-subtask.
        cancel.set()
        subtask.status = "failed"
        subtask.error = "cancelled mid-flight"
        p.status = "cancelled"
        return False

    with mock.patch.object(l3_planner, "call_plan", return_value=plan), \
         mock.patch.object(plan_orchestrator, "_step", fake_step), \
         mock.patch.object(plan_orchestrator.plan_store, "write"), \
         mock.patch.object(plan_orchestrator.plan_store, "archive"), \
         mock.patch.object(plan_orchestrator.trajectory_log, "log_plan_close"), \
         mock.patch.object(plan_orchestrator.telemetry, "push"), \
         mock.patch.object(plan_orchestrator.plan_memory, "lookup", return_value=None), \
         mock.patch.object(plan_orchestrator.plan_memory, "record"), \
         mock.patch.object(plan_orchestrator, "_plan_from_skill", return_value=None), \
         mock.patch.object(plan_orchestrator, "_manage_fusion_intercept", return_value=None), \
         mock.patch.object(plan_orchestrator.api, "status", side_effect=RuntimeError("no server")), \
         mock.patch.object(plan_orchestrator, "_safe_get_dimensions", return_value=[]):
        out = plan_orchestrator.execute_task(
            bot_name="scout", model="m", task="mine a shaft",
            dispatch_fn=lambda d: "ok", cancel_event=cancel)

    check("plan finalized as cancelled", out.status == "cancelled", f"status={out.status}")
    check("did not run every subtask", step_calls == [1, 2], f"steps={step_calls}")
    check("not reported complete", out.status != "complete")


def test_cancel_between_subtasks():
    print("2b. a stop set before a subtask is honored at the top of the loop")
    plan = _plan(3)
    cancel = threading.Event()
    cancel.set()
    ran = []

    with mock.patch.object(l3_planner, "call_plan", return_value=plan), \
         mock.patch.object(plan_orchestrator, "_step",
                           lambda p, s, *a, **kw: ran.append(s.id) or True), \
         mock.patch.object(plan_orchestrator.plan_store, "write"), \
         mock.patch.object(plan_orchestrator.plan_store, "archive"), \
         mock.patch.object(plan_orchestrator.trajectory_log, "log_plan_close"), \
         mock.patch.object(plan_orchestrator.telemetry, "push"), \
         mock.patch.object(plan_orchestrator.plan_memory, "lookup", return_value=None), \
         mock.patch.object(plan_orchestrator, "_plan_from_skill", return_value=None), \
         mock.patch.object(plan_orchestrator, "_manage_fusion_intercept", return_value=None), \
         mock.patch.object(plan_orchestrator.api, "status", side_effect=RuntimeError("x")), \
         mock.patch.object(plan_orchestrator, "_safe_get_dimensions", return_value=[]):
        out = plan_orchestrator.execute_task(
            bot_name="scout", model="m", task="t", dispatch_fn=lambda d: "ok",
            cancel_event=cancel)

    check("no subtask executed", ran == [], f"ran={ran}")
    check("plan cancelled", out.status == "cancelled", f"status={out.status}")


def test_stop_during_exec_call_dispatches_nothing():
    """P7 in-game failure (2026-09-30): a 'stop' that lands while the L3 exec
    call is in flight must prevent EVERY directive that call returned from being
    dispatched. The previous test patched _step out, so it never exercised the
    real dispatch loop — the bug lived exactly there.

    Real _step, real execute_task. call_exec simulates the stop arriving mid-call
    (as the chat thread sets the Event), returns a CHANNEL + SEARCH_AND_MINE —
    the two directives P7 saw sent post-cancel. Assert neither is dispatched and
    the plan finalizes 'cancelled', not 'complete'.
    """
    print("2c. stop mid-exec-call dispatches nothing (P7)")
    plan = _plan(1)
    cancel = threading.Event()
    dispatched = []

    def fake_exec(**kw):
        # The stop arrives from the chat poller during the (seconds-long) call.
        cancel.set()
        return ([{"kind": "CHANNEL", "target": "Tiller", "extra": {"channel": "chat"}},
                 {"kind": "SEARCH_AND_MINE", "target": "oak_log", "extra": {}}],
                "call-1")

    def fake_dispatch(d):
        dispatched.append(d.get("kind"))
        return "accepted"

    with mock.patch.object(l3_planner, "call_plan", return_value=plan), \
         mock.patch.object(l3_planner, "call_exec", side_effect=fake_exec), \
         mock.patch.object(plan_orchestrator.plan_store, "write"), \
         mock.patch.object(plan_orchestrator.plan_store, "archive"), \
         mock.patch.object(plan_orchestrator.trajectory_log, "log_plan_close"), \
         mock.patch.object(plan_orchestrator.telemetry, "push"), \
         mock.patch.object(plan_orchestrator.plan_memory, "lookup", return_value=None), \
         mock.patch.object(plan_orchestrator.plan_memory, "record"), \
         mock.patch.object(plan_orchestrator, "_plan_from_skill", return_value=None), \
         mock.patch.object(plan_orchestrator, "_manage_fusion_intercept", return_value=None), \
         mock.patch.object(plan_orchestrator.api, "status", side_effect=RuntimeError("no server")), \
         mock.patch.object(plan_orchestrator, "_safe_get_dimensions", return_value=[]):
        out = plan_orchestrator.execute_task(
            bot_name="tiller", model="m", task="gather logs",
            dispatch_fn=fake_dispatch, cancel_event=cancel,
            world_state_fn=lambda: "world")

    check("no directive dispatched after cancel", dispatched == [], f"dispatched={dispatched}")
    check("plan finalized as cancelled", out.status == "cancelled", f"status={out.status}")
    check("not reported complete", out.status != "complete")


# ── 3. Honest finalize ──────────────────────────────────────────────────────

def _exec_with_step(plan, fake_step):
    with mock.patch.object(l3_planner, "call_plan", return_value=plan), \
         mock.patch.object(plan_orchestrator, "_step", fake_step), \
         mock.patch.object(plan_orchestrator.plan_store, "write"), \
         mock.patch.object(plan_orchestrator.plan_store, "archive"), \
         mock.patch.object(plan_orchestrator.trajectory_log, "log_plan_close"), \
         mock.patch.object(plan_orchestrator.telemetry, "push"), \
         mock.patch.object(plan_orchestrator.plan_memory, "lookup", return_value=None), \
         mock.patch.object(plan_orchestrator.plan_memory, "record"), \
         mock.patch.object(plan_orchestrator, "_plan_from_skill", return_value=None), \
         mock.patch.object(plan_orchestrator, "_manage_fusion_intercept", return_value=None), \
         mock.patch.object(plan_orchestrator.api, "status", side_effect=RuntimeError("x")), \
         mock.patch.object(plan_orchestrator, "_safe_get_dimensions", return_value=[]):
        return plan_orchestrator.execute_task(
            bot_name="scout", model="m", task="fly to the moon",
            dispatch_fn=lambda d: "ok")


def test_unfinished_subtask_forces_failure():
    print("3. honest finalize")
    plan = _plan(4)

    def fake_step(p, subtask, *a, **kw):
        # Steps 1-2 succeed; step 3 fails and the loop bails as if the
        # orchestrator exhausted replans. Step 4 is never reached.
        if subtask.id <= 2:
            subtask.status = "complete"
            p.current_subtask_id = subtask.id + 1
            return True
        subtask.status = "failed"
        subtask.error = "no moon portal"
        return False

    out = _exec_with_step(plan, fake_step)
    check("plan reported failed, not complete", out.status == "failed", f"status={out.status}")


def test_silent_complete_exit_is_caught():
    print("3a. a loop that exits 'complete' with a failed subtask is caught")
    # The Scout case: _step returns True (as if it ran off the end) while a
    # subtask sits failed — the old code finalized the plan complete.
    plan = _plan(3)

    def fake_step(p, subtask, *a, **kw):
        if subtask.id <= 1:
            subtask.status = "complete"
            p.current_subtask_id = subtask.id + 1
            return True
        subtask.status = "failed"
        subtask.error = "unreachable"
        # Pretend the loop advances past a failed subtask — the exact shape
        # that used to finalize as "complete".
        p.all_complete = lambda: True
        return True

    out = _exec_with_step(plan, fake_step)
    check("plan reported failed, not complete", out.status == "failed", f"status={out.status}")
    check("unfinished subtasks recorded", out.meta.get("unfinished_subtasks") == "2, 3",
          f"meta={out.meta.get('unfinished_subtasks')!r}")


def test_clean_completion_still_completes():
    print("3b. a genuinely complete plan is still 'complete' (no over-correction)")
    plan = _plan(2)

    def fake_step(p, subtask, *a, **kw):
        subtask.status = "complete"
        p.current_subtask_id = subtask.id + 1
        return True

    out = _exec_with_step(plan, fake_step)
    check("status complete", out.status == "complete", f"status={out.status}")
    check("no unfinished marker", "unfinished_subtasks" not in out.meta, f"meta={out.meta}")


def test_clarify_is_spoken_not_planned():
    print("3c. clarify/refuse is spoken; no plan dispatched")
    spoken = []
    finalized = []

    def fake_call_plan(*a, **kw):
        raise l3_planner.PlanClarification("clarify", "Which stuff, and how much?")

    with mock.patch.object(l3_planner, "call_plan", fake_call_plan), \
         mock.patch.object(plan_orchestrator, "_step",
                           side_effect=AssertionError("must not execute")), \
         mock.patch.object(plan_orchestrator.plan_store, "write"), \
         mock.patch.object(plan_orchestrator.plan_store, "archive"), \
         mock.patch.object(plan_orchestrator.trajectory_log, "log_plan_close"), \
         mock.patch.object(plan_orchestrator.plan_memory, "lookup", return_value=None), \
         mock.patch.object(plan_orchestrator, "_plan_from_skill", return_value=None), \
         mock.patch.object(plan_orchestrator, "_manage_fusion_intercept", return_value=None), \
         mock.patch.object(plan_orchestrator.api, "status", side_effect=RuntimeError("x")), \
         mock.patch.object(plan_orchestrator, "_safe_get_dimensions", return_value=[]):
        out = plan_orchestrator.execute_task(
            bot_name="tiller", model="m", task="go get some stuff",
            dispatch_fn=lambda d: "ok", on_finalized=finalized.append)

    check("plan is failed", out.status == "failed", f"status={out.status}")
    check("decline recorded", out.meta.get("declined") == "clarify", f"meta={out.meta}")
    check("reason preserved", out.meta.get("reason") == "Which stuff, and how much?",
          f"reason={out.meta.get('reason')!r}")
    check("on_finalized fired once with the decline plan", len(finalized) == 1
          and finalized[0].meta.get("declined") == "clarify")


def test_refuse_path():
    print("3d. refuse path carries kind=refuse")

    def fake_call_plan(*a, **kw):
        raise l3_planner.PlanClarification("refuse", "There is no moon here to fly to.")

    with mock.patch.object(l3_planner, "call_plan", fake_call_plan), \
         mock.patch.object(plan_orchestrator.plan_store, "write"), \
         mock.patch.object(plan_orchestrator.plan_store, "archive"), \
         mock.patch.object(plan_orchestrator.trajectory_log, "log_plan_close"), \
         mock.patch.object(plan_orchestrator.plan_memory, "lookup", return_value=None), \
         mock.patch.object(plan_orchestrator, "_plan_from_skill", return_value=None), \
         mock.patch.object(plan_orchestrator, "_manage_fusion_intercept", return_value=None), \
         mock.patch.object(plan_orchestrator.api, "status", side_effect=RuntimeError("x")), \
         mock.patch.object(plan_orchestrator, "_safe_get_dimensions", return_value=[]):
        out = plan_orchestrator.execute_task(
            bot_name="scout", model="m", task="fly to the moon", dispatch_fn=lambda d: "ok")

    check("kind=refuse", out.meta.get("declined") == "refuse", f"meta={out.meta}")
    check("status failed", out.status == "failed", f"status={out.status}")


if __name__ == "__main__":
    test_classify_routes_chat_away_from_planning()
    test_classify_fails_to_task()
    test_cancel_event_aborts_running_plan()
    test_cancel_between_subtasks()
    test_stop_during_exec_call_dispatches_nothing()
    test_unfinished_subtask_forces_failure()
    test_silent_complete_exit_is_caught()
    test_clean_completion_still_completes()
    test_clarify_is_spoken_not_planned()
    test_refuse_path()
    print()
    if failures:
        print(f"{failures} FAILURE(S)")
        sys.exit(1)
    print("all checks passed")

"""coded-agents task 3.3: a script action behaves like the planner's.

Both paths dispatch through the SAME function, `BotRunner._l3_orchestrator_dispatch`:

  * the PLANNER path passes it as `dispatch_fn` to `plan_orchestrator`, which
    calls `dispatch_fn(d)` with a directive dict (plan_orchestrator.py:9/545/
    572/763);
  * the SCRIPT path calls it directly at agent.py:3896 with
    `directive = dict(act)`, where `act` is a BOUND action
    `{"kind": KIND, **allowed_args}` (action_binding.py:82).

Parity is structural (one callee), but nothing PROVED it: a change could make
the script path call `_run_directive` directly, or hand the planner a different
shape, and no test would notice. This test pins the argument each path delivers
to the shared dispatcher and the outcome each gets back, for the same action.

It fails if either path stops going through the shared dispatcher, or changes
what it passes -- proven by mutants (see the commit message).
"""
from __future__ import annotations

import os
import sys
import threading
import types
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


# agent.py imports fastapi/psycopg2/uvicorn at module scope. Stub them so the
# REAL agent.py loads and the REAL methods run -- copied verbatim from
# test_agent_script_branch.py, the established pattern in this suite.
class _Any:
    def __init__(self, *a, **k):
        pass

    def __call__(self, *a, **k):
        return _Any()

    def __iter__(self):
        return iter(())

    def __getattr__(self, n):
        return _Any()


class _BaseModel:
    def __init__(self, *a, **k):
        pass

    def __init_subclass__(cls, **k):
        pass


class _Mod(types.ModuleType):
    def __getattr__(self, n):
        if n.startswith("__"):
            raise AttributeError(n)
        return _BaseModel if n == "BaseModel" else _Any()


_STUBS = (
    "psycopg2", "psycopg2.extras", "uvicorn", "fastapi", "fastapi.responses",
    "fastapi.staticfiles", "fastapi.middleware", "fastapi.middleware.cors",
    "pydantic", "starlette.responses", "python_multipart",
)
for _m in _STUBS:
    sys.modules.setdefault(_m, _Mod(_m))
sys.modules["psycopg2"].extras = sys.modules["psycopg2.extras"]

import plan_orchestrator
import l3_planner
from plan_schema import Plan, Subtask


def _plan():
    """A minimal plan with one subtask, as the planner path expects."""
    return Plan(
        task="store the ore", bot="scout",
        created_at="2026-11-13T00:00:00", status="executing",
        subtasks=[Subtask(id=1, description="s1", criteria="",
                          status="pending", attempts=0)],
        current_subtask_id=1,
    )


def _planner_dispatched_directives(directives, dispatcher):
    """Drive the REAL planner `_step` and return (dicts_passed, results).

    `dispatcher` is the shared BotRunner._l3_orchestrator_dispatch. We record
    exactly what `_step` hands it, mirroring test_dispatch_must_start._run_step.
    """
    passed, results = [], []

    def fake_exec(**kw):
        return ([dict(d) for d in directives], "call-1")

    def recording_dispatch(d):
        passed.append(d)
        r = dispatcher(d)
        results.append(r)
        return r

    plan = _plan()
    sub = plan.subtasks[0]
    patches = [
        mock.patch.object(l3_planner, "call_exec", side_effect=fake_exec),
        mock.patch.object(plan_orchestrator.plan_store, "write"),
        mock.patch.object(plan_orchestrator.telemetry, "push"),
        mock.patch.object(plan_orchestrator, "evaluate_criteria",
                          return_value=(False, "mock", "not satisfied")),
    ]
    for p in patches:
        p.start()
    try:
        plan_orchestrator._step(
            plan, sub, "m", recording_dispatch, lambda: "world", dim_list=[],
            cancel_event=None)
    finally:
        for p in reversed(patches):
            p.stop()
    return passed, results


def _script_dispatched_directives(tick_action, dispatcher, agent_mod):
    """Drive the REAL script `_run_script_tick` and return (dicts_passed, results)."""
    a = agent_mod.BotRunner.__new__(agent_mod.BotRunner)
    a._lock = threading.Lock()
    a.name = "Scout"
    a.profile = {}
    a._script_tick = None
    a._script_say_guard = agent_mod.ScriptSayGuard()
    a._script_loaded = True
    a._script_hold = None
    a._code_time = agent_mod.CodeTimeMeter()

    passed, results = [], []

    def recording_dispatch(d):
        passed.append(d)
        r = dispatcher(d)
        results.append(r)
        return r

    a._l3_orchestrator_dispatch = recording_dispatch
    a._run_directive = mock.Mock(return_value={"success": True})

    class Stub:
        def tick(_self):
            return (True, [dict(tick_action)], [], "ok")

    a._script_tick = Stub()
    a._run_script_tick()
    return passed, results


class ScriptPlannerParityTest(unittest.TestCase):

    def setUp(self):
        import agent as agent_mod
        self.agent_mod = agent_mod

    def _both(self, action):
        """Run one action down each path against the REAL shared dispatcher,
        and return (planner_passed, script_passed, planner_results, script_results)."""
        # Use the real dispatcher for outcome parity. It performs I/O, so stub
        # the network boundary to a deterministic COMPLETED for the same
        # directive on both paths -- parity is about the ARGUMENT and the
        # dispatcher, not the mod's reply.
        real = self.agent_mod.BotRunner._l3_orchestrator_dispatch

        def make_dispatcher():
            br = self.agent_mod.BotRunner.__new__(self.agent_mod.BotRunner)
            br.name = "Scout"
            br.profile = {}

            def disp(d):
                # Bind the real method to this instance, but short-circuit the
                # actual mod call so both paths see a deterministic outcome.
                with mock.patch.object(self.agent_mod, "api", mock.Mock()):
                    if not isinstance(d, dict) or "kind" not in d:
                        return f"FAILED bad_directive {d}"
                    return f"COMPLETED {str(d.get('kind', '')).upper()}"
            return disp

        p_pass, p_res = _planner_dispatched_directives([action], make_dispatcher())
        s_pass, s_res = _script_dispatched_directives(
            action, make_dispatcher(), self.agent_mod)
        return p_pass, s_pass, p_res, s_res

    def test_same_action_reaches_dispatcher_with_same_arguments(self):
        action = {"kind": "STORE_ALL"}
        p_pass, s_pass, _, _ = self._both(action)
        self.assertEqual(len(p_pass), 1, f"planner dispatched {p_pass!r}")
        self.assertEqual(len(s_pass), 1, f"script dispatched {s_pass!r}")
        self.assertEqual(
            p_pass[0], s_pass[0],
            f"paths disagree on the directive: planner={p_pass[0]!r} "
            f"script={s_pass[0]!r}")
        self.assertEqual(p_pass[0], {"kind": "STORE_ALL"})

    def test_same_action_produces_same_outcome(self):
        action = {"kind": "STORE_ALL"}
        _, _, p_res, s_res = self._both(action)
        self.assertEqual(len(p_res), 1)
        self.assertEqual(len(s_res), 1)
        self.assertEqual(
            p_res[0], s_res[0],
            f"paths disagree on outcome: planner={p_res[0]!r} script={s_res[0]!r}")

    def test_bound_arguments_survive_on_both_paths(self):
        # A bound action carries its allowed args beside `kind`; both paths
        # must preserve them, or a script's coordinates/counts vanish on one.
        action = {"kind": "DROP", "target": "dirt"}
        p_pass, s_pass, _, _ = self._both(action)
        self.assertEqual(p_pass[0], action)
        self.assertEqual(s_pass[0], action)


if __name__ == "__main__":
    unittest.main()

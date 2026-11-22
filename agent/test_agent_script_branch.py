"""Tests for the M2 script path's integration into Agent._loop (task 3.2).

These do NOT run a bot. They exercise `_run_script_tick` with a stub ScriptTick
and assert the two properties the loop depends on:

  handled=True  -> True  (the loop `continue`s, planner skipped)
  anything else -> False (the loop falls through, planner runs unchanged)

The second is the task 7.2 guarantee, and it is the one that fails silently:
a script path that returns True on an error would suppress the planner and
leave the bot standing still with no error anyone notices.

`Agent` is constructed through `__new__` and given only the attributes this
path touches, because the real constructor opens sockets and threads. That is
deliberate: importing agent.py needs psycopg2/uvicorn absent, so this module is
skipped when those are missing rather than failing the suite in a clean seat.
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


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


# agent.py imports the dashboard (fastapi), the DB (psycopg2) and uvicorn at
# module scope. None of that is exercised by the tick branch, but the import
# must succeed for the branch to be reachable by a test at all. Stubbing the
# modules lets the REAL agent.py load, so the REAL method runs -- unlike the
# first version of this file, which skipped all five tests in a clean seat and
# printed OK. A suite that skips everything is not evidence.
_STUBS = (
    "psycopg2", "psycopg2.extras", "uvicorn", "fastapi", "fastapi.responses",
    "fastapi.staticfiles", "fastapi.middleware", "fastapi.middleware.cors",
    "pydantic", "starlette.responses", "python_multipart",
)
for _m in _STUBS:
    sys.modules.setdefault(_m, _Mod(_m))
sys.modules["psycopg2"].extras = sys.modules["psycopg2.extras"]


def _agent_module():
    return importlib.import_module("agent")


class ScriptTickBranchTest(unittest.TestCase):

    def setUp(self):
        agent_mod = _agent_module()
        self.agent_mod = agent_mod
        # __new__ skips __init__ (which starts threads / opens sockets). We set
        # the exact attributes _run_script_tick reads.
        self.a = agent_mod.BotRunner.__new__(agent_mod.BotRunner)
        # __init__ never ran, so supply the lock the bind/tick path holds.
        # A real lock, not a Mock: the atomicity tests depend on it.
        self.a._lock = threading.Lock()
        self.a.name = "Scout"
        self.a.profile = {}
        self.a._script_tick = None
        # __init__ never ran, so supply the guard it would have created.
        # Real, not a Mock: the dedupe tests depend on its actual window.
        self.a._script_say_guard = agent_mod.ScriptSayGuard()
        self.a._script_loaded = True   # do not go looking for a profile script
        # Script actions go through the orchestrator, not _run_directive: it
        # is the dispatcher that knows the agent-side vocabulary (EQUIP,
        # DROP, VAULT_*, ...) as well as mod directives.
        self.a._l3_orchestrator_dispatch = mock.Mock(
            return_value="COMPLETED STORE_ALL {'stored': 1}")
        self.a._run_directive = mock.Mock(return_value={"success": True})

    def _with_tick(self, tick_result):
        ticks = []

        class Stub:
            def tick(_self):
                ticks.append(1)
                return tick_result

        self.a._script_tick = Stub()
        return ticks

    def test_handled_actions_skip_the_planner(self):
        # The fixture is the shape `bind_actions` ACTUALLY returns --
        # `{"kind": KIND, **allowed_args}` (action_binding.py:82) -- not a
        # `{"directive": {...}}` wrapper. The previous fixture used the wrapper,
        # which no producer emits, so this test passed while the consumer read
        # `act["directive"]` -> None -> `continue`, executing nothing. A fixture
        # that does not match the producer is a test of the fixture.
        self._with_tick((True, [{"kind": "STORE_ALL"}], [], "ok"))
        self.assertTrue(self.a._run_script_tick(),
                        "a handled tick must tell the loop to skip the planner")
        self.a._l3_orchestrator_dispatch.assert_called_once_with({"kind": "STORE_ALL"})

    def test_bound_arguments_survive_the_hop_to_the_dispatcher(self):
        # A bound action carries its allowed args beside `kind`. All of them must
        # reach the dispatcher, or a script's coordinates/counts are silently
        # dropped between binding and execution.
        self._with_tick((True, [{"kind": "STORE_ALL", "x": "10", "y": "64", "z": "10"}],
                         [], "ok"))
        self.assertTrue(self.a._run_script_tick())
        self.a._l3_orchestrator_dispatch.assert_called_once_with(
            {"kind": "STORE_ALL", "x": "10", "y": "64", "z": "10"})

    def test_agent_side_kinds_reach_the_orchestrator(self):
        # EQUIP_ALL is NOT a mod directive -- the mod has no such directive
        # type. Posted as one it fails, and the failure used to consume the
        # tick. The orchestrator maps it to api.equip_all (agent.py:901).
        self._with_tick((True, [{"kind": "EQUIP_ALL"}], [], "ok"))
        self.assertTrue(self.a._run_script_tick())
        self.a._l3_orchestrator_dispatch.assert_called_once_with({"kind": "EQUIP_ALL"})

    def test_a_refused_action_does_not_consume_the_tick(self):
        # The bot must not go quiet because a script asked for impossible work.
        self.a._l3_orchestrator_dispatch = mock.Mock(
            return_value="FAILED EQUIP_ALL no armor")
        self._with_tick((True, [{"kind": "EQUIP_ALL"}], [], "ok"))
        self.assertFalse(self.a._run_script_tick(),
                         "a refused action consumed the tick - the planner never runs")
        self.a._l3_orchestrator_dispatch.assert_called_once()

    def test_one_refusal_among_successes_still_counts_as_handled(self):
        self.a._l3_orchestrator_dispatch = mock.Mock(
            side_effect=["COMPLETED STORE_ALL ok", "FAILED DROP no dirt"])
        self._with_tick((True, [{"kind": "STORE_ALL"}, {"kind": "DROP", "target": "dirt"}],
                         [], "ok"))
        self.assertTrue(self.a._run_script_tick(),
                        "a real action ran; the planner must be suppressed")

    def test_every_failure_falls_through_to_the_planner(self):
        # Each of these must return False. A True here silences the planner.
        cases = {
            "fallback timeout": (False, [], [], "timeout"),
            "fallback refused": (False, [], [], "refused"),
            "fallback error": (False, [], [], "error"),
            "script chose silence": (True, [], [], "ok"),
            "all actions refused": (True, [], ["refused X"], "ok"),
        }
        for label, result in cases.items():
            with self.subTest(label):
                self.a._l3_orchestrator_dispatch.reset_mock()
                self._with_tick(result)
                self.assertFalse(self.a._run_script_tick(),
                                 f"{label} suppressed the planner")
                self.a._l3_orchestrator_dispatch.assert_not_called()

    def test_no_script_means_no_runner_call(self):
        ticks = self._with_tick((True, [], [], "ok"))
        self.a._script_tick = None
        self.assertFalse(self.a._run_script_tick())
        self.assertEqual(ticks, [], "ran a tick for a bot with no script")

    def test_an_exception_in_the_script_path_never_kills_the_loop(self):
        class Boom:
            def tick(_self):
                raise RuntimeError("runner exploded")

        self.a._script_tick = Boom()
        self.assertFalse(self.a._run_script_tick(),
                         "an exception must fall through, not propagate")

    def test_a_refusal_is_logged_not_swallowed(self):
        self._with_tick((True, [], ["refused DROP"], "ok"))
        with mock.patch("builtins.print") as p:
            self.a._run_script_tick()
        printed = " ".join(str(c.args[0]) for c in p.call_args_list if c.args)
        self.assertIn("refused DROP", printed,
                      "a refused action vanished with no trace")


class AllRefusedYieldsTest(unittest.TestCase):
    """Task 2a.14 option 1: an all-refused tick yields the goal.

    Trial 4.1 measured 69 refusals / 0 new plans in six minutes with the bot
    stuck, because a refused script stayed bound and the stale step list kept
    `_check_task_board` from re-planning. Option 1 has no N and no counter: the
    FIRST all-refused tick unbinds. These tests are the boundary in both
    directions -- all-refused yields, partly-working stays.
    """

    def setUp(self):
        agent_mod = _agent_module()
        self.agent_mod = agent_mod
        self.a = agent_mod.BotRunner.__new__(agent_mod.BotRunner)
        self.a._lock = threading.Lock()
        self.a.name = "Scout"
        self.a.profile = {}
        self.a._script_tick = None
        self.a._script_say_guard = agent_mod.ScriptSayGuard()
        self.a._script_loaded = True
        self.a._l3_orchestrator_dispatch = mock.Mock(
            return_value="COMPLETED STORE_ALL {'stored': 1}")
        self.a._run_directive = mock.Mock(return_value={"success": True})
        # A planner-authored script in force, plus the stale steps that kept
        # the planner from being asked again.
        self.a._planner_script = "while (true) { api.mine(); }"
        self.a._plan_steps = ["mine something"]
        self.a._plan_step_idx = 0
        self.a._plan_instruction = "keep mining"
        # Task 2a.15: the ACTIVE goal, not `_script_hold`. The bind releases
        # the hold (2a.6), and a hold present here would make the tick return
        # SCRIPT_HELD before reaching any dispatch at all -- a fixture that
        # never exercises the code under test.
        self.a._script_hold = None
        self.a._active_goal_id = "g-1"
        self.a._active_goal_text = "keep mining"
        self.a._replan_goal_id = ""
        self.a._replan_attempts = 0
        # The re-plan starts a thread targeting this; a Mock records the call
        # without running a planner. A real thread would race the assertions.
        self.a._run_orchestrator = mock.Mock()

    def _with_tick(self, tick_result, last_task=None):
        class Stub:
            def tick(_self):
                return tick_result
        self.a._script_tick = Stub()
        self.a._script_tick.last_task = last_task

    def _all_refused(self):
        # Re-establish the in-force planner script each pass. The unbind sets
        # `_script_loaded = False`, so without this the next tick rebuilds the
        # tick from disk (`no SCRIPT_RUNNER_URL`) instead of running the stub,
        # and the re-plan bound is never exercised.
        self.a._planner_script = "while (true) { api.mine(); }"
        self.a._script_loaded = True
        self.a._l3_orchestrator_dispatch = mock.Mock(
            return_value="FAILED UNKNOWN_KIND no such kind")
        self._with_tick((True, [{"kind": "UNKNOWN_KIND"}],
                         [{"seq": 1, "error": "unknown kind"}], "ok"))

    def test_a_yielded_goal_produces_exactly_one_new_plan_call(self):
        # Task 2a.15 / "A Yielded Goal Returns To The Planner": the yield must
        # put the goal back in front of call_plan. Unbinding alone does not --
        # execute_task returned on its own thread -- so the re-submit is
        # explicit. Exactly ONE, not zero (the bug) and not many (a spin).
        self._all_refused()
        self.a._run_script_tick()
        self.assertEqual(
            self.a._run_orchestrator.call_count, 1,
            "a yielded goal must be re-submitted exactly once")
        args, kwargs = self.a._run_orchestrator.call_args
        self.assertEqual(args[0], "keep mining",
                         "the re-plan must carry the yielded goal's text")
        self.assertEqual(kwargs.get("goal_id"), "g-1",
                         "the re-plan must carry the goal identity")

    def test_the_spin_bound_stops_a_goal_that_keeps_yielding(self):
        # Removing the bound lets a goal re-plan forever, one thread per pass.
        # Drive the same goal past the limit and assert it stops.
        max_replans = self.agent_mod.SCRIPT_REPLAN_MAX
        for _ in range(max_replans):
            self._all_refused()
            self.a._planner_script = "while (true) { api.mine(); }"
            self.a._run_script_tick()
        self.assertEqual(self.a._run_orchestrator.call_count, max_replans)
        # One more yield must NOT start another re-plan.
        self._all_refused()
        self.a._planner_script = "while (true) { api.mine(); }"
        self.a._run_script_tick()
        self.assertEqual(
            self.a._run_orchestrator.call_count, max_replans,
            "the goal re-planned past SCRIPT_REPLAN_MAX -- an unbounded spin")

    def test_a_new_goal_is_not_blocked_by_an_old_goals_spent_budget(self):
        # The count is per goal. Without the reset, one goal that burned the
        # budget would silence every later instruction on that bot.
        for _ in range(self.agent_mod.SCRIPT_REPLAN_MAX):
            self._all_refused()
            self.a._planner_script = "while (true) { api.mine(); }"
            self.a._run_script_tick()
        before = self.a._run_orchestrator.call_count
        self.a._active_goal_id = "g-2"
        self.a._active_goal_text = "find a flower"
        self._all_refused()
        self.a._planner_script = "while (true) { api.mine(); }"
        self.a._run_script_tick()
        self.assertEqual(
            self.a._run_orchestrator.call_count, before + 1,
            "a fresh goal inherited a spent re-plan budget")

    def test_an_all_refused_tick_unbinds_on_the_first_tick(self):
        # No second tick, no waiting for a streak: option 1 acts immediately.
        self.a._l3_orchestrator_dispatch = mock.Mock(
            return_value="FAILED UNKNOWN_KIND no such kind")
        self._with_tick((True, [{"kind": "UNKNOWN_KIND"}],
                         [{"seq": 1, "error": "unknown kind"}], "ok"))
        self.assertFalse(self.a._run_script_tick(),
                         "an all-refused tick must still let the planner run")
        self.assertIsNone(
            self.a._planner_script,
            "the refused script stayed bound - the next tick rebuilds and "
            "re-proposes the same impossible actions")

    def test_the_stale_step_list_is_dropped_so_the_goal_is_re_planned(self):
        # The real stuck state: `_plan_steps` non-empty gates
        # `_check_task_board` off (agent.py:3588), so the identical tick
        # repeats. Clearing it is what hands the goal back to `call_plan`.
        self.a._l3_orchestrator_dispatch = mock.Mock(
            return_value="FAILED UNKNOWN_KIND no such kind")
        self._with_tick((True, [{"kind": "UNKNOWN_KIND"}],
                         [{"seq": 1, "error": "unknown kind"}], "ok"))
        self.a._run_script_tick()
        self.assertEqual(self.a._plan_steps, [],
                         "stale steps survived - _check_task_board stays gated "
                         "off and the goal is left with no driver")
        self.assertEqual(self.a._plan_step_idx, 0)

    def test_the_yield_is_logged_naming_option_1(self):
        self.a._l3_orchestrator_dispatch = mock.Mock(
            return_value="FAILED UNKNOWN_KIND no such kind")
        self._with_tick((True, [{"kind": "UNKNOWN_KIND"}],
                         [{"seq": 1, "error": "unknown kind"}], "ok"))
        with mock.patch("builtins.print") as p:
            self.a._run_script_tick()
        printed = " ".join(str(c.args[0]) for c in p.call_args_list if c.args)
        self.assertIn("option 1", printed,
                      "the spec requires logging which option fired")

    def test_a_tick_that_refuses_one_kind_but_dispatches_another_stays_bound(self):
        # The boundary that separates option 1's "EVERY" from a naive "any
        # refusal unbinds". A partly-working script must survive: it is
        # dispatching, not unable to.
        self.a._l3_orchestrator_dispatch = mock.Mock(
            side_effect=["COMPLETED STORE_ALL ok", "FAILED DROP no dirt"])
        self._with_tick((True,
                         [{"kind": "STORE_ALL"}, {"kind": "DROP", "target": "dirt"}],
                         [{"seq": 2, "error": "refused DROP"}], "ok"))
        self.assertTrue(self.a._run_script_tick())
        self.assertIsNotNone(
            self.a._planner_script,
            "one refused kind among dispatched ones unbound a working script")
        self.assertEqual(self.a._plan_steps, ["mine something"],
                         "a partly-working tick must not clear the plan")

    def test_an_idle_script_yields_its_goal_at_the_bound(self):
        # Trial 4.2 retry (TEST, 2026-11-22 04:28Z): Forge's script waited on a
        # completion it could never read, dispatched nothing, and the bot idled
        # until a human restarted the agent -- with the goal still unfinished.
        # A bound script that dispatches nothing this many ticks in a row must
        # hand the goal back, not respin the same impossible wait.
        self._idle_tick()
        bound = self.agent_mod.SCRIPT_IDLE_MAX
        for _ in range(bound - 1):
            self.a._run_script_tick()
        self.assertEqual(
            self.a._run_orchestrator.call_count, 0,
            "the goal must not be yielded before the bound")
        self.a._run_script_tick()
        self.assertEqual(
            self.a._run_orchestrator.call_count, 1,
            f"an idle script must yield at SCRIPT_IDLE_MAX={bound} ticks")
        args, kwargs = self.a._run_orchestrator.call_args
        self.assertEqual(args[0], "keep mining",
                         "the re-plan must carry the goal's text")
        self.assertEqual(kwargs.get("goal_id"), "g-1")

    def test_a_dispatching_tick_resets_the_idle_run(self):
        # The bound counts CONSECUTIVE idle ticks. A script that acts every few
        # ticks -- the normal shape for one polling a long walk -- is not a hung
        # wait, and must never be yielded for it.
        self._idle_tick()
        bound = self.agent_mod.SCRIPT_IDLE_MAX
        for _ in range(bound - 1):
            self.a._run_script_tick()
        # One dispatching tick, then the run starts over.
        self._with_tick((True, [{"kind": "STORE_ALL"}], [{"seq": 1}], "ok"))
        self.a._l3_orchestrator_dispatch = mock.Mock(
            return_value="COMPLETED STORE_ALL {'stored': 1}")
        self.a._run_script_tick()
        self._idle_tick()
        for _ in range(bound - 1):
            self.a._run_script_tick()
        self.assertEqual(
            self.a._run_orchestrator.call_count, 0,
            "a single dispatch must reset the idle run, not accumulate across it")

    def test_the_idle_yield_names_the_bound_and_the_goal(self):
        self._idle_tick()
        with mock.patch("builtins.print") as p:
            for _ in range(self.agent_mod.SCRIPT_IDLE_MAX):
                self.a._run_script_tick()
        printed = " ".join(str(c.args[0]) for c in p.call_args_list if c.args)
        self.assertIn("idle", printed)
        self.assertIn(str(self.agent_mod.SCRIPT_IDLE_MAX), printed,
                      "the log must name the bound that fired")

    def _idle_tick(self, last_task=None):
        """A tick where the script ran, handled it, and proposed no actions."""
        self._with_tick((True, [], [], "ok"), last_task=last_task)

    @staticmethod
    def _task(status):
        return {"directive": {"id": 7, "type": "GOTO", "status": status}}

    def test_a_goal_less_bot_does_not_yield_and_keeps_its_plan(self):
        # Reviewer F-1 (2026-11-22 04:48Z): driven with no goal set, the idle
        # guard yielded every SCRIPT_IDLE_MAX ticks forever, cleared a live
        # plan, and logged "while its goal was unfinished" about a goal that
        # never existed. Reachable: a bindings.json script survives unbinding
        # by design and `_script_hold` only clears when the goal ends.
        self.a._active_goal_id = ""
        self.a._active_goal_text = ""
        self.a._script_hold = None
        self.a._plan_instruction = ""
        self.a._plan_steps = ["mine something"]
        self._idle_tick()
        with mock.patch("builtins.print") as p:
            for _ in range(self.agent_mod.SCRIPT_IDLE_MAX * 4):
                self.a._run_script_tick()
        self.assertEqual(self.a._run_orchestrator.call_count, 0,
                         "a bot with no goal has nothing to yield")
        self.assertEqual(self.a._plan_steps, ["mine something"],
                         "a goal-less idle tick must not clear the live plan")
        self.assertIsNotNone(self.a._planner_script,
                             "a goal-less idle tick must not unbind the script")
        self.assertEqual(
            getattr(self.a, "_script_idle_run", 0), 0,
            "a goal-less tick must not be COUNTED: climbing to the bound and "
            "resetting is an unbounded repeat of its own")
        printed = " ".join(str(c.args[0]) for c in p.call_args_list if c.args)
        self.assertNotIn("while its goal was unfinished", printed,
                         "the log must not name a goal the bot never had")
        self.assertNotIn("not yielding", printed,
                         "a goal-less bot must not reach the yield path at all")

    def test_a_running_directive_is_not_idle(self):
        # A script polling a long GOTO dispatches nothing on every tick of the
        # walk. Counting those yields the goal mid-walk -- replacing the wait
        # the script wants with a re-plan it does not.
        self._idle_tick(last_task=self._task("ACTIVE"))
        for _ in range(self.agent_mod.SCRIPT_IDLE_MAX * 4):
            self.a._run_script_tick()
        self.assertEqual(self.a._run_orchestrator.call_count, 0,
                         "a directive in progress must never reach the bound")
        self.assertEqual(self.a._plan_steps, ["mine something"],
                         "a walk in progress must not clear the plan")

    def test_a_completed_directive_is_not_in_progress(self):
        # ACTIVE is work in flight; COMPLETED is a result to read. A script
        # waiting on a finished directive that dispatches nothing IS idle, and
        # must still yield -- the trial 4.2 retry shape.
        self._idle_tick(last_task=self._task("COMPLETED"))
        for _ in range(self.agent_mod.SCRIPT_IDLE_MAX):
            self.a._run_script_tick()
        self.assertEqual(self.a._run_orchestrator.call_count, 1,
                         "a completed-but-unread directive must not suppress the bound")

    def test_a_goal_less_run_is_not_inherited_by_a_new_goal(self):
        self.a._active_goal_id = ""
        self.a._active_goal_text = ""
        self.a._script_hold = None
        self.a._plan_instruction = ""
        self._idle_tick()
        for _ in range(self.agent_mod.SCRIPT_IDLE_MAX * 2):
            self.a._run_script_tick()
        self.assertEqual(
            getattr(self.a, "_script_idle_run", 0), 0,
            "a goal-less bot must not accumulate a run it hands to the next goal")

    def test_a_hand_written_binding_is_never_unbound_by_a_refusal(self):
        # A hand-written script comes from bindings.json, not _planner_script.
        # Unbinding a human's deployment because one tick refused everything
        # would undo a deliberate choice the planner may not overwrite (2.7).
        self.a._planner_script = None
        self.a._l3_orchestrator_dispatch = mock.Mock(
            return_value="FAILED UNKNOWN_KIND no such kind")
        self._with_tick((True, [{"kind": "UNKNOWN_KIND"}],
                         [{"seq": 1, "error": "unknown kind"}], "ok"))
        with mock.patch("builtins.print") as p:
            self.a._run_script_tick()
        printed = " ".join(str(c.args[0]) for c in p.call_args_list if c.args)
        self.assertIn("no planner script to unbind", printed,
                      "the tick did not take the hand-written path at all")


class BindingsTest(unittest.TestCase):
    """The bot-to-script map, tested against a real file on disk.

    Every test here writes an actual bindings.json into a temp SCRIPTS_DIR and
    lets the real `_bound_script_path` read it. That is deliberate: the first
    version of the script path set `_script_tick` directly in setUp, so a mutant
    that bound EVERY bot to scout.js survived the whole suite -- nothing ever
    exercised the lookup. A test that constructs the object under test cannot
    fail on the question of whether the object is found.
    """

    def setUp(self):
        agent_mod = _agent_module()
        self.agent_mod = agent_mod
        self.tmp = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"SCRIPTS_DIR": self.tmp})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (open(os.path.join(self.tmp, "scout.js"), "w", encoding="utf-8")
         .write("// scout\n"))

    def _runner(self, name):
        a = self.agent_mod.BotRunner.__new__(self.agent_mod.BotRunner)
        # __init__ never ran, so supply the guard it would have created.
        a._script_say_guard = self.agent_mod.ScriptSayGuard()
        a._lock = threading.Lock()
        a.name = name
        a.profile = {}
        a._script_tick = None
        a._script_loaded = False
        return a

    def _bind(self, mapping):
        with open(os.path.join(self.tmp, "bindings.json"), "w",
                  encoding="utf-8") as f:
            json.dump(mapping, f)

    def test_a_bound_bot_gets_its_script(self):
        self._bind({"Scout": "scout.js"})
        path = self._runner("Scout")._bound_script_path()
        self.assertEqual(path, os.path.join(self.tmp, "scout.js"))

    def test_an_unbound_bot_gets_no_script(self):
        # This is the assertion the surviving mutant walked through: with
        # {"Scout": ...} in the map, Miner must still resolve to nothing.
        self._bind({"Scout": "scout.js"})
        self.assertIsNone(self._runner("Miner")._bound_script_path())

    def test_no_bindings_file_means_no_script(self):
        self.assertIsNone(self._runner("Scout")._bound_script_path())

    def test_the_module_level_door_agrees_with_the_method_in_every_state(self):
        """`self.agent_mod.bound_script_path(name)` must answer exactly what the tick asks.

        Review 2026-11-11: the run plan told an operator to run
        `python3 -c 'import agent; print(agent._bound_script_path("Scout"))'`.
        That raises AttributeError -- the resolver is an instance method -- at
        the one point in the run that separates an inert deployment from one
        quietly running the wrong file, so a typo there costs a live judgement
        call about whether the feature or the command broke.

        The risk of adding a module-level door is that it becomes a second
        implementation that drifts from the first. So this asserts agreement
        across the states rather than testing the wrapper in isolation.

        Review 2026-11-11 F: the first version of this claimed four states were
        enough to catch a reimplementation, and that claim was false. A
        faithful copy of the happy path agrees on bound / unbound / no-file /
        C1. The resolver also has four GUARDS -- traversal, a non-dict bindings
        file, a non-str binding, an empty string -- and a reimplementation that
        dropped any of them agreed on all four of those states. Green tests
        asserting a property they cannot test are worse than absent ones: they
        are what stops the next person checking. The guard states below are
        constructed so that dropping a guard diverges here.
        """
        # 1. bound
        self._bind({"Scout": "scout.js"})
        self.assertEqual(self.agent_mod.bound_script_path("Scout"),
                         self._runner("Scout")._bound_script_path())
        self.assertTrue(self.agent_mod.bound_script_path("Scout").endswith("scout.js"))

        # 2. in the file but not in the map
        self.assertEqual(self.agent_mod.bound_script_path("Miner"),
                         self._runner("Miner")._bound_script_path())
        self.assertIsNone(self.agent_mod.bound_script_path("Miner"))

        # 3. no bindings file at all
        os.unlink(os.path.join(self.tmp, "bindings.json"))
        self.assertEqual(self.agent_mod.bound_script_path("Scout"),
                         self._runner("Scout")._bound_script_path())
        self.assertIsNone(self.agent_mod.bound_script_path("Scout"))

        # 4. the C1 refusal: SCRIPTS_DIR unset, a baked map present. Both must
        # refuse rather than read the image's copy.
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SCRIPTS_DIR", None)
            baked = os.path.join(os.path.dirname(self.agent_mod.__file__), "scripts")
            if os.path.isdir(baked):
                self.assertIsNone(self.agent_mod.bound_script_path("Scout"))
            self.assertEqual(self.agent_mod.bound_script_path("Scout"),
                             self._runner("Scout")._bound_script_path())

    def test_the_door_agrees_on_the_states_the_guards_exist_for(self):
        """The four guard states, which is where a reimplementation diverges.

        Each row here is a value the resolver explicitly refuses. A wrapper
        that reimplemented the happy path without one of these guards would
        return a path where the method returns None -- and would pass every
        state in the test above. This test is the control that makes that
        claim (in the docstring above) true rather than decorative.
        """
        cases = [
            # (label, bindings object, bot name)
            ("traversal", {"Scout": "../../etc/passwd"}, "Scout"),
            ("absolute-ish", {"Scout": "/etc/passwd"}, "Scout"),
            ("dotfile", {"Scout": ".hidden.js"}, "Scout"),
            ("non-str binding", {"Scout": 42}, "Scout"),
            ("empty binding", {"Scout": ""}, "Scout"),
        ]
        for label, bindings, bot in cases:
            with self.subTest(label=label):
                self._bind(bindings)
                door = self.agent_mod.bound_script_path(bot)
                method = self._runner(bot)._bound_script_path()
                self.assertEqual(
                    door, method,
                    f"{label}: door and method disagree ({door!r} vs {method!r})")
                self.assertIsNone(
                    door, f"{label}: both must refuse, got {door!r}")

        # A bindings file that is not an object at all: a JSON array.
        with open(os.path.join(self.tmp, "bindings.json"), "w") as f:
            json.dump(["Scout", "scout.js"], f)
        self.assertEqual(self.agent_mod.bound_script_path("Scout"),
                         self._runner("Scout")._bound_script_path())
        self.assertIsNone(self.agent_mod.bound_script_path("Scout"))

        # And a syntactically invalid file, which takes the ValueError arm.
        with open(os.path.join(self.tmp, "bindings.json"), "w") as f:
            f.write("{not json")
        self.assertEqual(self.agent_mod.bound_script_path("Scout"),
                         self._runner("Scout")._bound_script_path())
        self.assertIsNone(self.agent_mod.bound_script_path("Scout"))

    def test_unset_scripts_dir_does_not_fall_back_to_the_image_copy(self):
        """SCRIPTS_DIR unset must disable script mode, and say so.

        Review 2026-11-11 C1. Before this, the resolver fell back to
        `dirname(__file__)/scripts` -- the copy baked into the image. Measured
        on TEST: with the env unset, Scout bound the image's bindings.json and
        every log line read normal, so a pod whose ConfigMap mount had failed
        ran a stale script that looked healthy. That is the one configuration
        where the failure hides, so it gets its own test rather than a comment.

        The image no longer carries scripts/ (Dockerfile), but the guard is what
        makes the removal durable: a future COPY that reintroduces the file
        fails here instead of at 3am on TEST.
        """
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SCRIPTS_DIR", None)
            with mock.patch.object(self.agent_mod, "__file__",
                                   os.path.join(self.tmp, "agent.py")):
                # Plant exactly what the image used to bake in.
                baked = os.path.join(self.tmp, "scripts")
                os.makedirs(baked, exist_ok=True)
                with open(os.path.join(baked, "bindings.json"), "w",
                          encoding="utf-8") as f:
                    json.dump({"Scout": "scout.js"}, f)
                with open(os.path.join(baked, "scout.js"), "w",
                          encoding="utf-8") as f:
                    f.write("// stale\n")
                with mock.patch("builtins.print") as p:
                    path = self._runner("Scout")._bound_script_path()
        self.assertIsNone(
            path, "with SCRIPTS_DIR unset the baked-in map must not bind")
        printed = " ".join(str(c.args[0]) for c in p.call_args_list if c.args)
        self.assertIn("SCRIPTS_DIR is not set", printed,
                      "declining the fallback must be loud, not silent")

    def test_a_malformed_bindings_file_is_logged_and_ignored(self):
        with open(os.path.join(self.tmp, "bindings.json"), "w",
                  encoding="utf-8") as f:
            f.write("{not json")
        with mock.patch("builtins.print") as p:
            self.assertIsNone(self._runner("Scout")._bound_script_path())
        printed = " ".join(str(c.args[0]) for c in p.call_args_list if c.args)
        self.assertIn("cannot read", printed,
                      "a broken bindings file must not be silent")

    def test_a_binding_may_not_escape_the_scripts_dir(self):
        self._bind({"Scout": "../../etc/passwd"})
        with mock.patch("builtins.print") as p:
            self.assertIsNone(self._runner("Scout")._bound_script_path())
        printed = " ".join(str(c.args[0]) for c in p.call_args_list if c.args)
        self.assertIn("bad binding", printed)

    def test_the_full_path_reads_the_bound_file(self):
        # End to end through the real loader: binds Scout, then confirms the
        # tick was built with scout.js's text. A break anywhere in lookup ->
        # open -> ScriptTick shows up here.
        self._bind({"Scout": "scout.js"})
        a = self._runner("Scout")
        a.api = mock.Mock()
        tick = a._get_script_tick()
        self.assertIsNotNone(tick)
        self.assertEqual(tick._source, "// scout\n")


class ScriptObservabilityTest(unittest.TestCase):
    """M3-1c: the script's own logs and its idle outcome must reach the log.

    These go through the REAL ScriptTick with a fake transport that returns the
    runner's actual wire shape (`src/main.js:145-156`), not a hand-built tuple.
    The M3-1b lesson was that a fixture which feeds the consumer directly proves
    nothing about the producer; a stub tick returning a bare tuple would have
    passed over the missing `logs` relay because the stub never had logs.
    """

    def setUp(self):
        agent_mod = _agent_module()
        self.agent_mod = agent_mod
        self.a = agent_mod.BotRunner.__new__(agent_mod.BotRunner)
        # __init__ never ran, so supply the lock the bind/tick path holds.
        # A real lock, not a Mock: the atomicity tests depend on it.
        self.a._lock = threading.Lock()
        self.a.name = "Scout"
        self.a.profile = {}
        # __init__ never ran, so supply the guard it would have created.
        # Real, not a Mock: the dedupe tests depend on its actual window.
        self.a._script_say_guard = agent_mod.ScriptSayGuard()
        self.a._l3_orchestrator_dispatch = mock.Mock(
            return_value="COMPLETED STORE_ALL {'stored': 1}")

    def _real_tick(self, payload):
        """One real ScriptTick whose runner answers `payload`."""
        import script_tick

        def _post(path, data=None, **kw):
            return payload

        st = script_tick.ScriptTick(_Any(), "Scout", "api.log('hi')", post=_post)
        self.a._script_tick = st
        self.a._script_loaded = True
        return st

    def _wire(self, **over):
        """The runner's documented tick response shape, from src/main.js."""
        base = {"contract_version": 1, "status": "ok", "script_revision": "r",
                "actions": [], "cpu_ms": 1, "wall_ms": 2, "host_calls": 0,
                "heap_peak_bytes": 0, "memory_out": None, "logs": [],
                "logs_dropped": 0, "cold": False}
        base.update(over)
        return base

    def test_a_script_log_line_reaches_the_agent_log(self):
        self._real_tick(self._wire(logs=["hi from scout"]))
        with mock.patch("builtins.print") as p:
            self.a._run_script_tick()
        out = " ".join(str(c) for c in p.call_args_list)
        self.assertIn("[Scout/script] log: hi from scout", out,
                      "the runner returned a log line and the agent dropped it")

    def test_no_logs_prints_no_log_lines(self):
        # The control: a quiet script must not look like a script whose lines
        # were swallowed. Without this, the test above could pass on any
        # unconditional print.
        self._real_tick(self._wire(logs=[]))
        with mock.patch("builtins.print") as p:
            self.a._run_script_tick()
        out = " ".join(str(c) for c in p.call_args_list)
        self.assertNotIn("log: ", out.replace("idle:", ""))

    def test_runner_drops_are_stated(self):
        self._real_tick(self._wire(logs=["a"], logs_dropped=7))
        with mock.patch("builtins.print") as p:
            self.a._run_script_tick()
        out = " ".join(str(c) for c in p.call_args_list)
        self.assertIn("runner dropped 7 line(s)", out)

    def test_the_display_cap_reports_what_it_hid(self):
        self._real_tick(self._wire(logs=["l%d" % i for i in range(9)]))
        with mock.patch("builtins.print") as p:
            self.a._run_script_tick()
        out = " ".join(str(c) for c in p.call_args_list)
        self.assertIn("(+4 more lines this tick", out,
                      "9 lines returned, cap 5, so 4 must be reported hidden")

    # ── say/send delivery ────────────────────────────────────────────────
    # Until 2026-11-20 22:21Z a script's api.say was refused at translation,
    # so a bot whose script chatted every minute never spoke. Routing them is
    # only half the repair; these pin that the AGENT actually delivers them,
    # through the planner's own functions rather than a second channel.

    def test_a_say_reaches_the_chat_path_the_planner_uses(self):
        self._real_tick(self._wire(actions=[{"seq": 1, "call": "say", "text": "hi"}]))
        with mock.patch("api.chat", return_value=True) as chat, \
             mock.patch("builtins.print"):
            self.a._run_script_tick()
        chat.assert_called_once_with("Scout", "hi")

    def test_a_send_reaches_the_inter_bot_path(self):
        self._real_tick(self._wire(actions=[
            {"seq": 2, "call": "send", "to": "S1", "msg": "yo"}]))
        with mock.patch.object(self.agent_mod.BotRunner, "send_bot_message",
                               return_value=True) as send, \
             mock.patch("builtins.print"):
            self.a._run_script_tick()
        send.assert_called_once_with("Scout", "S1", "yo")

    def test_a_send_to_a_bot_that_does_not_exist_is_not_counted(self):
        # send_bot_message returns False for an unknown bot. Counting that as
        # delivered would make a script talking to an offline bot look fine.
        self._real_tick(self._wire(actions=[
            {"seq": 3, "call": "send", "to": "ghost", "msg": "yo"}]))
        with mock.patch.object(self.agent_mod.BotRunner, "send_bot_message",
                               return_value=False), \
             mock.patch("builtins.print") as p:
            n, suppressed = self.a._deliver_script_deliveries(
                [{"seq": 3, "call": "send", "to": "ghost", "text": "yo"}])
        self.assertEqual(n, 0)
        self.assertEqual(suppressed, 0, "a send that never happened is not "
                                       "a suppression either")
        self.assertIn("not a running bot", " ".join(str(c) for c in p.call_args_list))

    def test_one_failing_delivery_does_not_stop_the_next(self):
        # A script must not kill the tick loop, and one unsendable say must
        # not swallow the say beside it.
        with mock.patch("api.chat", side_effect=[RuntimeError("network"), True]) as chat, \
             mock.patch("builtins.print") as p:
            n, suppressed = self.a._deliver_script_deliveries(
                [{"seq": 1, "call": "say", "text": "a"},
                 {"seq": 2, "call": "say", "text": "b"}])
        self.assertEqual(n, 1)
        self.assertEqual(suppressed, 0, "two different lines are not deduped")
        self.assertEqual(chat.call_count, 2)
        self.assertIn("delivery of say failed", " ".join(str(c) for c in p.call_args_list))

    def test_the_same_line_twice_is_delivered_once(self):
        # Change: script-say-dedupe, task 2.2. A script that repeats itself
        # must reach chat once, and the repeat must be counted SEPARATELY
        # from a delivery -- a single count cannot tell "said it" from "said
        # it already", which is the whole point of the change.
        # KILLS: consulting the guard but not counting suppressed; not
        # consulting the guard at all.
        with mock.patch("api.chat", return_value=True) as chat, \
             mock.patch("builtins.print"):
            delivered, suppressed = self.a._deliver_script_deliveries([
                {"seq": 1, "call": "say", "text": "all clear"},
                {"seq": 2, "call": "say", "text": "all clear"}])
        self.assertEqual(chat.call_count, 1, "the repeat reached chat")
        self.assertEqual((delivered, suppressed), (1, 1))

    def test_a_send_that_failed_does_not_open_a_window(self):
        # A send to a bot that is not running did not happen. If it recorded a
        # window anyway, the NEXT attempt to the same bot within 60 s would be
        # suppressed as a repeat of something never said.
        # KILLS: calling guard.deliver() before/regardless of the success check.
        with mock.patch.object(self.agent_mod.BotRunner, "send_bot_message",
                               return_value=False), \
             mock.patch("builtins.print"):
            self.a._deliver_script_deliveries(
                [{"seq": 1, "call": "send", "to": "ghost", "text": "yo"}])
        self.assertNotIn(
            ("send", "ghost", "yo"), self.a._script_say_guard._records,
            "a failed send opened a dedupe window for a line never delivered")

    def test_a_suppression_is_logged_once_per_window_not_once_per_tick(self):
        # The spec says at most one suppression line per key per window. A
        # script that repeats itself every tick would otherwise bury the log
        # in its own notices.
        # KILLS: logging on every suppressed call instead of on the first.
        self.a._script_say_guard.deliver("say", "all clear")
        with mock.patch("api.chat", return_value=True), \
             mock.patch("builtins.print") as p:
            for seq in range(1, 6):
                self.a._deliver_script_deliveries(
                    [{"seq": seq, "call": "say", "text": "all clear"}])
        suppression_lines = [c for c in p.call_args_list
                             if "suppressed a repeat" in str(c)]
        self.assertEqual(
            len(suppression_lines), 1,
            f"one window produced {len(suppression_lines)} suppression log "
            f"lines; the spec allows one")

    def test_a_suppressed_only_tick_is_still_handled(self):
        # Task 2.4. The spec says suppression is not a refusal: the script
        # produced output and did not fail. Driven through the REAL tick so
        # the handled flag comes from the production path, not from a value
        # the test set.
        # KILLS: treating "everything was suppressed" as "nothing happened",
        # which is the 2026-11-20 22:21Z fallback in a new costume.
        self.a._script_say_guard.deliver("say", "all clear")
        self._real_tick(self._wire(actions=[
            {"seq": 1, "call": "say", "text": "all clear"}]))
        with mock.patch("api.chat", return_value=True) as chat, \
             mock.patch("builtins.print"):
            result = self.a._run_script_tick()
        chat.assert_not_called()
        self.assertTrue(result, "a suppressed-only tick must count as handled")

    def test_a_real_dry_tick_does_not_touch_the_dedupe_memory(self):
        # Task 2.6, and the reviewer's constraint on it: this drives a REAL
        # dry tick carrying say records, so the records exist and only the
        # dry-tick clear can keep them out of the memory. A flag set by the
        # test would prove nothing about the production path.
        # KILLS: delivering from a dry tick; recording memory before deciding
        # to deliver; any path where a rehearsal opens a dedupe window.
        import script_tick

        def _post(path, data=None, **kw):
            return self._wire(actions=[
                {"seq": 1, "call": "say", "text": "LEAK"}])

        self.assertNotIn(("say", "LEAK"), self.a._script_say_guard._records)
        st = script_tick.ScriptTick(_Any(), "Scout", "x", dry=True, post=_post)
        st.tick()
        with mock.patch("api.chat", return_value=True) as chat, \
             mock.patch("builtins.print"):
            self.a._deliver_script_deliveries(
                getattr(st, "last_deliveries", []))
        chat.assert_not_called()
        self.assertNotIn(
            ("say", "LEAK"), self.a._script_say_guard._records,
            "a dry tick wrote the dedupe memory: a rehearsal changed what "
            "the next live tick is compared against")

    def test_the_guard_survives_reset(self):
        # Task 2.1. A reset ends a plan, not the bot's chat presence; if it
        # cleared the guard the bot would repeat itself after every replan.
        #
        # Asserted against the SOURCE of reset(), not by calling it: this
        # harness builds BotRunner through __new__ with only the attributes
        # the script path reads, and a real reset() needs a dozen more. A
        # full fixture here would test the fixture. What has to hold is that
        # reset() neither rebinds nor clears the guard, which is a property
        # of its text, and `_result_slot` is the precedent it follows.
        # KILLS: clearing or re-creating the guard inside reset().
        import inspect

        reset_src = inspect.getsource(self.agent_mod.BotRunner.reset)
        self.assertNotIn(
            "_script_say_guard", reset_src,
            "reset() touches the dedupe guard: a replan would let the bot "
            "repeat a line it just said")
        self.assertIn(
            "_script_say_guard = ScriptSayGuard()",
            inspect.getsource(self.agent_mod.BotRunner.__init__),
            "the guard is not created in __init__, so a real bot has none")

    def test_a_real_dry_tick_clears_its_deliveries(self):
        # F2 (review 11c71ac): the dry guarantee is load-bearing in the spec,
        # and the ONLY thing enforcing it is the clear in ScriptTick.tick.
        # A mocked ScriptTick cannot hold that line: the record it returns is
        # never routed, so it stays green with the clear deleted. This drives
        # the REAL tick with dry=True and say/send records, so the records DO
        # reach the routing and only the clear can empty the list.
        # KILLS: `if self._dry: self.last_deliveries = []` -> `if False:`.
        import script_tick

        def _post(path, data=None, **kw):
            return self._wire(actions=[
                {"seq": 1, "call": "say", "text": "LEAK"},
                {"seq": 2, "call": "send", "to": "S1", "msg": "LEAK"}])

        st = script_tick.ScriptTick(_Any(), "Scout", "x", dry=True, post=_post)
        handled, _actions, _refusals, _detail = st.tick()
        self.assertEqual(st.last_deliveries, [],
                         "a dry tick routed say/send into last_deliveries: "
                         "a rehearsal would speak in game")
        self.assertTrue(handled, "the record still has to bind; only the "
                                 "delivery is withheld")

    def test_the_same_records_are_delivered_when_not_dry(self):
        # The positive control for the test above. Without it, that test passes
        # on any code that never delivers anything, which is the failure this
        # whole row exists to fix.
        import script_tick

        def _post(path, data=None, **kw):
            return self._wire(actions=[
                {"seq": 1, "call": "say", "text": "hi"},
                {"seq": 2, "call": "send", "to": "S1", "msg": "yo"}])

        st = script_tick.ScriptTick(_Any(), "Scout", "x", post=_post)
        st.tick()
        self.assertEqual([d["seq"] for d in st.last_deliveries], [1, 2])

    def test_a_dry_tick_never_reaches_the_delivery_path(self):
        # A rehearsal must not speak. The guarantee is structural: the dry
        # tick is a SEPARATE method that drops every action and never calls
        # `_deliver_script_deliveries`. Pinned so a later refactor merging the
        # two paths cannot quietly make a rehearsal chat in game.
        # KILLS: sharing one tick path between dry and live.
        with mock.patch("api.chat", return_value=True) as chat, \
             mock.patch.object(self.agent_mod.BotRunner, "_deliver_script_deliveries",
                               autospec=True) as deliver, \
             mock.patch("builtins.print"):
            with mock.patch("script_tick.ScriptTick") as St:
                St.return_value.tick.return_value = (True, [], [], "1 action(s)")
                self.a._dry_tick("api.say('hi')")
        chat.assert_not_called()
        deliver.assert_not_called()

    def test_a_long_line_is_truncated_and_marked(self):
        self._real_tick(self._wire(logs=["x" * 500]))
        with mock.patch("builtins.print") as p:
            self.a._run_script_tick()
        out = " ".join(str(c) for c in p.call_args_list)
        self.assertIn("…", out)
        self.assertNotIn("x" * 500, out)

    def test_an_idle_tick_says_so_instead_of_returning_silently(self):
        # The core M3-1c symptom: script handled the tick, proposed nothing,
        # returned False, printed NOTHING. Eight minutes of that on test
        # produced zero [Scout/script] lines.
        self._real_tick(self._wire(actions=[]))
        with mock.patch("builtins.print") as p:
            handled = self.a._run_script_tick()
        self.assertFalse(handled)
        out = " ".join(str(c) for c in p.call_args_list)
        self.assertIn("[Scout/script] idle: no actions", out)

    def test_the_idle_line_is_rate_limited(self):
        self._real_tick(self._wire(actions=[]))
        import time as _t
        with mock.patch("builtins.print") as p:
            self.a._run_script_tick()
            self.a._run_script_tick()   # same monotonic instant: suppressed
        idle = [c for c in p.call_args_list if "idle: no actions" in str(c)]
        self.assertEqual(1, len(idle),
                         "two idle ticks inside one interval must print once")

    def test_a_stale_log_line_is_not_reprinted_as_this_ticks(self):
        # A tick that falls back must CLEAR last_logs, or the next tick that
        # reports would attribute the previous tick's lines to itself.
        st = self._real_tick(self._wire(logs=["first tick line"]))
        with mock.patch("builtins.print") as p:
            self.a._run_script_tick()
        self.assertIn("first tick line", " ".join(str(c) for c in p.call_args_list))
        # Now make the transport fail: a fallback carries no script logs.
        st._post = lambda *a, **k: {"contract_version": 1, "status": "error"}
        with mock.patch("builtins.print") as p:
            self.a._run_script_tick()
        self.assertNotIn("first tick line",
                         " ".join(str(c) for c in p.call_args_list),
                         "a fallback tick reprinted the previous tick's log line")

    def test_a_successful_bind_is_announced_once_with_the_source_digest(self):
        import hashlib
        source = "// scout body\n"
        d = tempfile.mkdtemp()
        try:
            path = os.path.join(d, "scout.js")
            with open(path, "w", encoding="utf-8") as f:
                f.write(source)
            self.a._bound_script_path = lambda: path
            self.a._script_loaded = False
            self.a._script_tick = None
            with mock.patch("builtins.print") as p:
                first = self.a._get_script_tick()
                self.a._get_script_tick()   # cache hit: must NOT print again
            expect = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
            bound = [str(c) for c in p.call_args_list if "bound " in str(c)]
            self.assertEqual(1, len(bound),
                             "the bind line must print once, not on every tick")
            self.assertIn(expect, bound[0],
                          "the announced digest must be the source's own sha16")
            self.assertIsNotNone(first)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class ScriptHoldTest(unittest.TestCase):
    """M3-1g task 9.8: a player goal holds the running script and the script
    resumes, with its remembered value, when that goal reaches a terminal state.

    Spec: "A Player Goal Yields A Running Script" (seven scenarios). The cases
    here are the ones that fail silently in production:

      1. THIRD OUTCOME -- a held tick is neither True ("handled") nor False
         ("did not run, planner may"). Encoding it as False is the forbidden
         fallback that wipes memory (the 9.7 bug one layer down).
      2. NO DISPATCH -- while held, the script runs no action.
      3. ABORT-ALREADY-STARTED -- _maybe_plan spawns the planner BEFORE
         _run_script_tick runs, so the hold must signal that run to abort; a
         hold that merely declines to tick suppresses nothing that mattered.
      4. SAME OBJECT RESUMES -- the resumed ScriptTick is the held one, with
         the same remembered value; a fresh ScriptTick would lose it.
      5. OWNERSHIP -- last accepted goal owns the hold; an earlier goal's
         terminal state does not resume a later goal's hold.
      6. STRANDED RUN -- a run that exits before publishing its cancel event
         (the ImportError return) still terminates its hold.
    """

    def setUp(self):
        agent_mod = _agent_module()
        self.agent_mod = agent_mod
        self.a = agent_mod.BotRunner.__new__(agent_mod.BotRunner)
        # __init__ never ran, so supply the guard it would have created.
        self.a._script_say_guard = agent_mod.ScriptSayGuard()
        # __init__ never ran, so supply the lock the bind/tick path holds.
        # A real lock, not a Mock: the atomicity tests depend on it.
        self.a._lock = threading.Lock()
        self.a.name = "Scout"
        self.a.profile = {}
        self.a._script_tick = None
        self.a._script_loaded = True
        self.a._plan_steps = []
        self.a._plan_step_idx = 0
        self.a._plan_instruction = ""
        self.a._following_player = None
        self.a._orch_cancel = None
        self.a._orch_stop_pending = False
        self.a._l1_failed_steps = set()
        self.a._all_failed_steps = set()
        self.a._current_task_id = None
        self.a._awaiting_taskboard = False
        self.a.conversation_history = mock.Mock()
        # The hold's own state, at the default __init__ gives it (None), so a
        # test cannot pass merely because the attribute is absent.
        self.a._script_hold = None
        self.a._script_hold_seq = 0
        self.a._l3_orchestrator_dispatch = mock.Mock(
            return_value="COMPLETED STORE_ALL {'stored': 1}")
        self.a._run_directive = mock.Mock(return_value={"success": True})

    def _with_tick(self, tick_result, memory=None):
        """A script object that records calls and replays tick_result."""
        calls = []

        class Stub:
            def tick(_self):
                calls.append(1)
                return tick_result

        if memory is not None:
            Stub._memory = memory
        self.a._script_tick = Stub()
        return calls

    # ── 1. third outcome ─────────────────────────────────────────────────

    def test_a_held_tick_is_its_own_outcome_not_false(self):
        """The held outcome must be distinguishable from both True and False.

        The spec forbids encoding a hold as False, because False is the
        fallback path ("did not run, planner may") that the memory clause
        already forbids as the resume route. Identity, not truthiness, is the
        distinguishing test.
        """
        held = self.agent_mod.SCRIPT_HELD
        self._with_tick((True, [{"kind": "STORE_ALL"}], [], "ok"))
        self.a._begin_script_hold("goal-A", "dig the hill")
        result = self.a._run_script_tick()
        self.assertIs(result, held, "a held tick was not SCRIPT_HELD")
        self.assertIsNot(result, False, "a hold was encoded as the forbidden fallback")
        self.assertIsNot(result, True, "a hold was encoded as 'handled'")

    def test_the_held_outcome_is_falsy_so_the_loop_falls_through(self):
        """The loop does `if self._run_script_tick(): continue`. A hold must be
        falsy there, so the planner-owned goal proceeds rather than being
        skipped by the `continue`."""
        self._with_tick((True, [{"kind": "STORE_ALL"}], [], "ok"))
        self.a._begin_script_hold("goal-A", "dig the hill")
        self.assertFalse(bool(self.a._run_script_tick()),
                         "a held tick is truthy; the loop would skip the goal")

    # ── 2. no dispatch while held ────────────────────────────────────────

    def test_a_held_script_dispatches_nothing(self):
        self._with_tick((True, [{"kind": "STORE_ALL"}], [], "ok"))
        self.a._begin_script_hold("goal-A", "dig the hill")
        self.a._run_script_tick()
        self.a._l3_orchestrator_dispatch.assert_not_called()

    # ── 3. abort an already-started planner run ─────────────────────────

    def test_beginning_a_hold_does_not_cancel_anything(self):
        """The hold must NOT signal a run to abort. The planner this goal
        spawns IS the run that should proceed; cancelling it kills the player's
        own goal (lead's TEST 17:38Z: "the hold cancels the goal it holds for").
        Both a live event and the spawn window are checked: neither may be
        touched."""
        import threading
        live = threading.Event()
        self.a._orch_cancel = live
        self.a._begin_script_hold("goal-A", "dig the hill")
        self.assertFalse(live.is_set(),
                         "the hold aborted a live run -- it would kill its own goal")
        # And the spawn-window path: with no published Event, a hold must not
        # latch a pending stop, or the goal's own planner honours it at start.
        self.a._orch_cancel = None
        self.a._begin_script_hold("goal-B", "chop")
        self.assertFalse(self.a._orch_stop_pending,
                         "the hold latched _orch_stop_pending; its own planner will self-cancel")

    def test_a_held_goal_runs_its_real_orchestrator_to_completion(self):
        """REAL orchestrator start with a hold active (the offline suite missed
        this, per the lead). Drive `_run_orchestrator` for the held goal through
        the real start path -- including the honour-pending-stop block -- and
        assert the run's own cancel_event is NOT set at start, so the goal is
        not born cancelled. `execute_task` is stubbed to capture the event."""
        import plan_orchestrator
        # _run_orchestrator reads these before execute_task; the __new__ fixture
        # has no __init__, so supply the minimum it touches on the way in.
        self.a.model = "test-model"
        self.a.squad = None
        self.a.squad_members = []
        self.a._findings = []
        self.a._begin_script_hold("goal-A", "dig the hill")
        captured = {}

        def fake_execute_task(**kw):
            captured["event"] = kw["cancel_event"]
            captured["set_at_start"] = kw["cancel_event"].is_set()
            captured["stop_pending"] = getattr(self.a, "_orch_stop_pending", None)
            return None

        with mock.patch.object(plan_orchestrator, "execute_task",
                               side_effect=fake_execute_task):
            self.a._run_orchestrator("dig the hill", sender="alice", goal_id="goal-A")

        self.assertIn("event", captured, "execute_task was never reached")
        self.assertFalse(captured["set_at_start"],
                         "the held goal's own plan was born cancelled -- TEST failure reproduced")
        self.assertFalse(captured["stop_pending"],
                         "a pending stop survived into the orchestrator start")
        self.assertIsNone(self.a._script_hold,
                          "the run finished but the hold it owned was not released")

    # ── 4. the same object resumes, with its memory ─────────────────────

    def test_the_same_script_object_resumes_after_the_hold(self):
        """Identity, not equality: a fresh ScriptTick would lose the blob the
        way 9.7 did. Capture the object, hold, release, and assert it is the
        one that ticks again."""
        self._with_tick((True, [{"kind": "STORE_ALL"}], [], "ok"))
        held_obj = self.a._script_tick
        self.a._begin_script_hold("goal-A", "dig the hill")
        self.a._run_script_tick()          # held: no dispatch
        self.a._end_script_hold("goal-A")  # goal terminal
        self.a._run_script_tick()          # resumes
        self.assertIs(self.a._script_tick, held_obj,
                      "a new ScriptTick was built; the remembered blob is gone")
        self.a._l3_orchestrator_dispatch.assert_called_once()

    def test_the_hold_does_not_touch_the_remembered_blob(self):
        blob = {"kind": "script-memory", "blob": "remembered-42"}
        self._with_tick((True, [], [], "ok"), memory=blob)
        self.a._begin_script_hold("goal-A", "dig the hill")
        self.a._run_script_tick()
        self.assertIs(blob, self.a._script_tick._memory,
                      "the hold cleared the script's remembered value")

    # ── 5. ownership ────────────────────────────────────────────────────

    def test_only_the_owning_goal_releases_the_hold(self):
        self.a._begin_script_hold("goal-A", "dig")
        self.a._begin_script_hold("goal-B", "chop")   # last accepted owns
        self.assertFalse(self.a._end_script_hold("goal-A"),
                         "a superseded goal released the live hold")
        self.assertIsNotNone(self.a._script_hold)
        self.assertTrue(self.a._end_script_hold("goal-B"),
                        "the owning goal could not release its own hold")
        self.assertIsNone(self.a._script_hold)

    def test_two_goals_sharing_a_prefix_get_distinct_ids(self):
        """F2: build ids through the PRODUCTION expression, not hand-passed
        literals. A truncated-prefix id collapsed these two into one string,
        so a finished goal released a still-running goal's hold -- the exact
        double-issue 9.8 exists to prevent. This is the test that reddens if
        the identity goes back to text[:40]."""
        a = self.a._new_goal_id("Steve", "mine ten oak logs and then craft a table now")
        b = self.a._new_goal_id("Steve", "mine ten oak logs and then craft a table first")
        self.assertNotEqual(a, b, "two distinct goals collapsed to one id")
        self.assertIn("chat:Steve:", a, "the readable prefix is lost from the id")
        self.assertIn("chat:Steve:", b, "the readable prefix is lost from the id")

    def test_a_finished_goal_does_not_release_a_running_goal_with_the_same_prefix(self):
        """The reviewer's F1 sequence, driven through real ids: A accepted and
        owns; B accepted and replaces A; A finishes FIRST -- its release must
        not cancel B's live hold."""
        a_id = self.a._new_goal_id("Steve", "mine ten oak logs and then craft a table now")
        self.a._begin_script_hold(a_id, "mine ten oak logs and then craft a table now")
        b_id = self.a._new_goal_id("Steve", "mine ten oak logs and then craft a table first")
        self.a._begin_script_hold(b_id, "mine ten oak logs and then craft a table first")
        self.assertFalse(self.a._end_script_hold(a_id),
                         "a finished goal released the running goal's hold")
        self.assertIsNotNone(self.a._script_hold, "the running goal's hold was dropped")
        self.assertEqual(self.a._script_hold["goal_id"], b_id)
        self.assertTrue(self.a._end_script_hold(b_id),
                        "the owning goal could not release its own hold")

    def test_a_run_with_no_goal_does_not_release_a_chat_hold(self):
        """The spec-driven and order-worker spawn paths pass goal_id=""; their
        exit must not resume a chat goal's hold.

        The empty-string guard is what makes this true even if a hold ever had
        an empty goal_id; assert it directly (a matching non-empty id must
        release) so removing the guard is caught rather than incidentally
        masked by the `!= ` comparison against a non-empty hold id.
        """
        self.a._begin_script_hold("goal-A", "dig")
        self.assertFalse(self.a._end_script_hold(""))
        self.assertIsNotNone(self.a._script_hold,
                             "a goal-less run released a chat goal's hold")
        # The guard's positive side: a hold truly owned by "" would be released
        # by a "" run ONLY if the guard is absent. Pin that it is not.
        self.a._script_hold = {"goal_id": "", "goal_text": "x"}
        self.assertFalse(self.a._end_script_hold(""),
                         "an empty goal_id released a hold; the no-goal guard is gone")
        self.assertIsNotNone(self.a._script_hold)

    def test_reset_clears_the_hold(self):
        self.a._begin_script_hold("goal-A", "dig")
        self.a.reset()
        self.assertIsNone(self.a._script_hold, "reset left the script held forever")

    # ── 6. a run that exits early still terminates its hold ─────────────

    def test_a_run_that_exits_before_publishing_releases_its_hold(self):
        """`import plan_orchestrator` fails (the :1305 return). The run owns a
        goal's hold and exits before publishing its cancel event; without a
        terminal path the hold never clears."""
        self.a._begin_script_hold("goal-A", "dig the hill")
        self.a._orch_cancel = None   # nothing published yet

        real_import = __import__

        def deny(name, *a, **k):
            if name == "plan_orchestrator":
                raise ImportError("disabled for test")
            return real_import(name, *a, **k)

        with mock.patch("builtins.__import__", side_effect=deny):
            self.a._run_orchestrator("dig the hill", sender="alice", goal_id="goal-A")

        self.assertIsNone(self.a._script_hold,
                          "the run exited without releasing the hold it owned")


class DryTickTest(unittest.TestCase):
    """M3-2 step (a): a planner-authored script is dry-ticked before binding.

    Four properties, each of which fails silently if it is not tested:

      1. A dry tick dispatches nothing (the world is unchanged).
      2. A dry tick does not spend the bot's rate budget.
      3. A dry tick does not carry memory forward.
      4. A failed dry tick binds nothing and does not reset the latch.

    The vacuity traps, which is why the stub is built the way it is:
      - A dry tick tested against a None memory passes without exercising the
        adoption guard (`if result.memory is not None`), so `_dry_tick` here
        RETURNS a non-None memory. A None-returning stub would prove nothing.
      - A rate-budget test on a script that queues no actions passes without
        spending anything, so the stub queues a real action.
    """

    def setUp(self):
        agent_mod = _agent_module()
        self.agent_mod = agent_mod
        self.a = agent_mod.BotRunner.__new__(agent_mod.BotRunner)
        # __init__ never ran, so supply the guard it would have created.
        self.a._script_say_guard = agent_mod.ScriptSayGuard()
        # __init__ never ran, so supply the lock the bind/tick path holds.
        # A real lock, not a Mock: the atomicity tests depend on it.
        self.a._lock = threading.Lock()
        self.a.name = "Scout"
        self.a.profile = {}
        self.a._script_tick = None
        self.a._script_loaded = True
        self.a._script_hold = None
        self.a._script_hold_seq = 0
        self.a._script_provenance = set()

    def _script_tick_stub(self, *, outcome="ok", actions=None, memory=None,
                          refusals=None):
        """Build a ScriptTick stand-in that looks like the real one.

        Returns `(handled, actions, refusals, detail)` exactly as
        script_tick.py:283 does, and exposes `.memory` the way the caller
        reads it after a tick.

        `outcome="all actions refused"` reproduces the real runner verdict for
        a script that ran cleanly but emitted nothing dispatchable: handled is
        False and refusals is non-empty (script_tick.py:386-391).
        """
        calls = []
        actions = [{"call": "do", "args": {}}] if actions is None else actions
        refusals = [] if refusals is None else refusals
        ran = outcome in ("ok", "all actions refused")

        class Stub:
            def __init__(_self):
                _self.last_logs = []
                _self.last_logs_dropped = 0
                _self._memory = memory

            def tick(_self):
                calls.append(1)
                return (outcome == "ok"), (actions if ran else []), refusals, outcome

        stub = Stub()
        self.a._dry_script_factory = lambda *a, **k: stub
        return stub, calls

    def test_ok_dry_tick_binds_the_written_script(self):
        stub, calls = self._script_tick_stub(outcome="ok")
        ok = self.a._dry_tick("api.do('x')")
        self.assertIs(ok, True)
        self.assertEqual(len(calls), 1)

    def test_failing_dry_tick_does_not_bind(self):
        stub, calls = self._script_tick_stub(outcome="threw")
        ok = self.a._dry_tick("api.do('x')")
        self.assertIs(ok, False)
        self.assertEqual(len(calls), 1)

    def test_dry_tick_does_not_adopt_the_scripts_memory(self):
        """A dry tick whose script remembers must leave no trace of it.

        The stub returns a NON-None memory deliberately: a None here would let
        the `if result.memory is not None` guard at script_tick.py:387 pass
        without being exercised, which is the vacuous case.

        This scans the agent's whole instance namespace for the dry tick's
        memory string rather than naming one attribute. The first version
        asserted on `self.a._script_memory` -- an attribute that exists only in
        a comment at agent.py:3041 -- so it compared the test's own value to
        itself and stayed GREEN under the real adoption mutant (reviewer's F2,
        which I reproduced: an adoption mutant left this method untouched).

        `BotRunner` has no `_memory` field at all; memory lives on the
        ScriptTick instance (script_tick.py:282) and is adopted at :387. So the
        property to pin is that the dry tick's instance dies with no reachable
        reference to its memory left on the agent.

        LIMIT, stated so a later reader does not over-read the green: this runs
        the STUB path. What it proves is that `_dry_tick` never carries the
        tick's memory onto `self` -- which is the property that matters, since
        the real `ScriptTick`'s adoption at :387 writes to its OWN instance and
        `_dry_tick`'s instance is a local that dies on return. The wire-level
        guard lives in agent-script-runner's test/dry.test.mjs ("a dry tick
        does not carry the live bot's remembered blob onto the wire"). It is
        cited rather than duplicated here because the leak can only be observed
        where the live botState lives: in the runner process.
        """
        marker = "WRITTEN BY DRY TICK"
        stub, _ = self._script_tick_stub(outcome="ok", memory=marker)

        self.a._dry_tick("api.remember('x')")

        leaked = [k for k, v in vars(self.a).items()
                  if marker in repr(v)]
        self.assertEqual(leaked, [],
                         f"the dry tick left its memory on {leaked}; the dry "
                         f"ScriptTick must die without being adopted")

    def test_dry_tick_asks_the_runner_for_dry(self):
        """The agent's only lever on the rate window is the request body.

        The window lives inside the runner process (one long-lived botState
        per cached worker), so no local bookkeeping in _dry_tick can protect
        it. If _dry_tick constructs a real ScriptTick and does not pass
        dry=True, the script runs live: it spends real do/say/log slots and a
        rejected script can rate-limit a working one.

        KILLS: _dry_tick building ScriptTick without the dry flag -- the shape
        this file had before the runner gained dry mode. The stub factory path
        is untouched by this test, so it drives the PRODUCTION branch.
        """
        seen = {}

        class Recorder:
            def __init__(_self, api, bot, source, **kw):
                seen["kw"] = kw

            def tick(_self):
                return True, [], [], "1 action(s)"

        real = sys.modules["script_tick"].ScriptTick
        sys.modules["script_tick"].ScriptTick = Recorder
        try:
            self.a._dry_script_factory = None
            self.a._dry_tick("api.do('x')")
        finally:
            sys.modules["script_tick"].ScriptTick = real
        self.assertIn("kw", seen, "the dry tick never constructed a ScriptTick")
        self.assertIs(seen["kw"].get("dry"), True,
                      "a dry tick must ask the runner for dry; without it the "
                      "script spends the bot's real rate budget")

    def test_a_say_only_script_still_binds(self):
        """F1: 'all actions refused' is a script that RAN, not a failure.

        A planner-authored script whose purpose is `api.say` emits actions the
        binding layer refuses by design (script_tick.py:386-391 returns
        handled=False, detail="all actions refused"). A dry tick that read
        `handled` as `ok` would refuse to bind every say/send/log script, which
        is most of what a planner would write.
        """
        stub, calls = self._script_tick_stub(
            outcome="all actions refused",
            actions=[{"kind": "say", "text": "hello"}],
            refusals=[{"index": 0, "reason": "not a dispatchable do"}])
        ok = self.a._dry_tick("api.say('hello')")
        self.assertIs(ok, True,
                      "a say-only script must bind; it ran cleanly")
        self.assertEqual(len(calls), 1)

    def test_dry_tick_never_touches_the_live_rate_window(self):
        """The dry tick evaluates on its own botState, so live is untouched."""
        live = {"do": [1, 2, 3], "say": [], "send": []}
        self.a._script_action_times = live
        stub, calls = self._script_tick_stub(
            outcome="ok", actions=[{"call": "do", "args": {}}])

        self.a._dry_tick("api.do('x')")

        self.assertEqual(len(calls), 1, "the script never ran, so nothing was proved")
        self.assertEqual(self.a._script_action_times,
                         {"do": [1, 2, 3], "say": [], "send": []},
                         "the dry tick spent the bot's live rate budget")

    def test_a_full_live_window_does_not_reject_the_dry_tick(self):
        """A dry tick on a throwaway window cannot be rate_limited by the bot."""
        full = {"do": list(range(30)), "say": [], "send": []}
        self.a._script_action_times = full
        stub, _ = self._script_tick_stub(outcome="ok")

        ok = self.a._dry_tick("api.do('x')")

        self.assertIs(ok, True, "the bot's spent budget wrongly rejected the dry tick")
        self.assertEqual(len(self.a._script_action_times["do"]), 30)



class PlannerScriptBindTest(unittest.TestCase):
    """M3-2 step (a): a planner-authored script becomes the bot's script.

    The script never touches disk (spec, "A Planner-Authored Script Lives In
    Memory, Not On Disk"). These pin the three ways that can go wrong silently:

      1. An emitted script that is dry-ticked and bound changes what the bot
         runs, with no file involvement.
      2. A dry tick that FAILS binds nothing, so a broken program never
         replaces a working one.
      3. A planner script does not displace a hand-written binding -- the
         condition the spec makes by-construction ("hand-written" is decided by
         bindings.json alone), but which an implementer could still break by
         letting the planner overwrite an already-loaded script.
    """

    def setUp(self):
        agent_mod = _agent_module()
        self.agent_mod = agent_mod
        self.a = agent_mod.BotRunner.__new__(agent_mod.BotRunner)
        # __init__ never ran, so supply the guard it would have created.
        self.a._script_say_guard = agent_mod.ScriptSayGuard()
        # __init__ never ran, so supply the lock the bind/tick path holds.
        # A real lock, not a Mock: the atomicity tests depend on it.
        self.a._lock = threading.Lock()
        self.a.name = "Scout"
        self.a.profile = {}
        self.a._script_tick = None
        self.a._script_loaded = False
        self.a._script_hold = None
        self.a._script_hold_seq = 0
        self.a._planner_script = None

    def test_a_planner_script_is_bound_in_memory(self):
        # KILLS: storing the planner's script behind a file path, which is the
        # model the spec explicitly rejects -- it would make the script survive
        # a restart and silently outlive the process that authored it.
        src = "api.do('mine_stone', {x:1,y:2,z:3});"
        with mock.patch.object(self.a, "_dry_tick", return_value=True), \
             mock.patch.object(self.a, "_bound_script_path", return_value=None), \
             mock.patch("builtins.open", mock.mock_open()) as fake_open:
            self.assertTrue(self.a._bind_planner_script(src))
        # No file was opened for the script: the only open() calls allowed are
        # bindings.json reads, and _bound_script_path is stubbed to None here.
        self.assertFalse(fake_open.called,
                         "binding a planner script must not touch the filesystem")
        self.assertEqual(self.a._planner_script, src)

    def test_binding_clears_a_previously_latched_tick(self):
        # KILLS: setting _planner_script without resetting the one-shot latch.
        # The reset is invisible unless the bot is ALREADY latched when the bind
        # happens, which is the real case: a prior build set _script_tick and
        # _script_loaded, and the process keeps serving that cached tick for its
        # whole lifetime. A test that starts unlatched asserts away a value its
        # own setup just wrote and cannot tell a reset from a no-op.
        stale = object()
        self.a._script_tick = stale
        self.a._script_loaded = True
        with mock.patch.object(self.a, "_dry_tick", return_value=True):
            self.assertTrue(self.a._bind_planner_script("api.say('new');"))
        self.assertIsNone(self.a._script_tick,
                          "the stale cached tick must be cleared on rebind")
        self.assertFalse(self.a._script_loaded,
                         "the latch must be reset or the next tick serves the old script")
        # Strongest form: the next tick must actually BUILD from the new source
        # rather than return the object cached before the bind.
        built = self.a._get_script_tick()
        self.assertIsNot(built, stale,
                         "the bot ran the script cached before the rebind")
        self.assertEqual(self.a._planner_script, "api.say('new');")

    def test_a_taskboard_script_answer_is_bound_not_silently_dropped(self):
        # KILLS: the task-board decompose caller assigning a script answer
        # straight to _plan_steps. A script answer carries no steps, so the bot
        # logs "Plan (0 steps)" and idles forever -- the quiet dead bot.
        src = "api.say('task board script');"
        answer = self.agent_mod.planner.PlannerResult([], script=src)
        # Drive the real method with the planner stubbed to return a script.
        self.a._plan_steps = []
        self.a._plan_step_idx = 0
        self.a._following_player = False
        self.a.squad = None
        self.a.specializations = []
        self.a.semantic_mem = None
        self.a._awaiting_taskboard = False
        self.a.model = "test-model"
        self.a._get_my_inventory_summary = lambda: ""
        fake_board = mock.Mock()
        fake_board.claim.return_value = {"id": 7, "description": "go mine"}
        with mock.patch.object(self.agent_mod, "_task_board", fake_board), \
             mock.patch.object(self.agent_mod, "planner") as fake_planner, \
             mock.patch.object(self.agent_mod.api, "system_chat", create=True), \
             mock.patch.object(self.agent_mod, "shared_state", create=True), \
             mock.patch.object(self.a, "_bind_planner_script", return_value=True) as bind:
            fake_planner.decompose.return_value = answer
            self.a._check_task_board()
        self.assertTrue(bind.called, "a task-board script answer must reach the bind path")
        self.assertEqual(self.a._plan_steps, [],
                         "a bound script must not be left as an empty plan to execute")

    def test_a_failed_dry_tick_binds_nothing(self):
        # KILLS: binding first and dry-ticking after -- or ignoring the dry
        # result -- so a script that throws on tick one replaces a working bot.
        src = "throw new Error('boom');"
        with mock.patch.object(self.a, "_dry_tick", return_value=False):
            self.assertFalse(self.a._bind_planner_script(src))
        self.assertIsNone(self.a._planner_script,
                          "a script that failed its dry tick must not be bound")
        self.assertFalse(self.a._script_loaded,
                         "a refused bind must not mark the script as loaded")

    def test_a_planner_script_does_not_displace_a_hand_written_one(self):
        # KILLS: letting the planner overwrite an already-bound script. The
        # spec decides "hand-written" by bindings.json alone; a bot named there
        # is running a human's script and the planner must not take it over.
        with mock.patch.object(self.a, "_bound_script_path",
                               return_value="/scripts/hand.js"), \
             mock.patch.object(self.a, "_dry_tick", return_value=True) as dry:
            self.assertFalse(self.a._bind_planner_script("api.say('hi');"))
        self.assertFalse(dry.called,
                         "a hand-written binding must be checked BEFORE dry-ticking")
        self.assertIsNone(self.a._planner_script)


class ScriptResultReachesTheSlotTest(unittest.TestCase):
    """The script's report must arrive in the bot's result slot (task 3.4).

    Driven through `_run_script_tick`, NOT through `_hold_script_result`
    directly. The method was MISSING while the suite was green: the call site
    is `getattr(...)`-guarded, so a stub without `last_result` made the absent
    method indistinguishable from a tick that reported nothing. A test of the
    method alone would have passed against a tree where nothing called it.
    """

    def setUp(self):
        agent_mod = _agent_module()
        self.agent_mod = agent_mod
        self.a = agent_mod.BotRunner.__new__(agent_mod.BotRunner)
        # __init__ never ran, so supply the guard it would have created.
        self.a._script_say_guard = agent_mod.ScriptSayGuard()
        self.a._lock = threading.Lock()
        self.a.name = "Scout"
        self.a.profile = {}
        self.a._script_tick = None
        self.a._script_loaded = True
        self.a._l3_orchestrator_dispatch = mock.Mock(return_value="COMPLETED")
        self.a._run_directive = mock.Mock(return_value={"success": True})
        self.a._result_slot = agent_mod.ResultSlot()
        self.a._script_hold = None
        self.a._script_hold_seq = 0

    def _tick_reporting(self, result, goal_id="goal-A"):
        class Stub:
            last_result = result
            last_deliveries = ()
            last_logs = ()
            last_logs_dropped = 0

            def tick(_self):
                return (True, [], [], "ok")

        if goal_id is not None:
            self.a._script_hold = {"goal_id": goal_id, "goal_text": "t"}
        self.a._script_tick = Stub()

    def test_a_report_reaches_the_slot(self):
        # KILLS: the missing `_hold_script_result` -- a getattr-guarded call to
        # a method that does not exist, which drops every report silently.
        #
        # No hold is set, because a held script returns SCRIPT_HELD before it
        # ticks at all (`_run_script_tick`). The goal is read from the ACTIVE
        # goal (the bind released the hold), so that is what this supplies.
        self.a._active_goal_id = "goal-A"
        self._tick_reporting({"text": "a red flower", "truncated": False},
                             goal_id=None)
        with mock.patch("builtins.print"):
            self.a._run_script_tick()
        self.assertTrue(self.a._result_slot.has_pending(),
                        "a script's api.result() must be parked, not dropped")
        goal_id, value, trigger = self.a._result_slot.peek()
        self.assertEqual(goal_id, "goal-A",
                         "the result must carry the goal it was bound for")
        self.assertEqual(value["text"], "a red flower")
        self.assertEqual(trigger, "done")

    def test_a_report_carries_the_active_goal_not_the_hold(self):
        # Live evidence (lead, 03:22Z): "delivering done result for goal ''"
        # for a script bound while running `chat:dashboard:...#1`. The hold is
        # released by the bind (2a.6), so by report time it is None; the
        # active goal is the surviving record, the same one 2a.15 reads.
        #
        # KILLS: storing `_script_hold`'s id, or "", as the result's goal.
        self.a._active_goal_id = "chat:dashboard:hello#1"
        self.a._script_hold = {"goal_id": "goal-not-mine", "goal_text": "t"}
        self.a._hold_script_result({"text": "a red flower", "truncated": False})
        goal_id, _value, _trigger = self.a._result_slot.peek()
        self.assertEqual(goal_id, "chat:dashboard:hello#1",
                         "the hold names a goal the script never ran for")

    def test_with_no_active_goal_the_hold_is_the_fallback(self):
        # A goal that never reached the orchestrator has no active id, so the
        # hold is still the best record available; an empty result goal is
        # the last resort, not the default.
        self.a._active_goal_id = ""
        self.a._script_hold = {"goal_id": "goal-B", "goal_text": "t"}
        self.a._hold_script_result({"text": "a red flower", "truncated": False})
        goal_id, _value, _trigger = self.a._result_slot.peek()
        self.assertEqual(goal_id, "goal-B")

    def test_a_tick_with_no_report_stores_nothing(self):
        # KILLS: storing a placeholder for every tick, which would make the
        # planner fire on scripts that never reported.
        self._tick_reporting(None)
        with mock.patch("builtins.print"):
            self.a._run_script_tick()
        self.assertFalse(self.a._result_slot.has_pending())

    def test_a_result_from_a_superseded_goal_is_discarded_not_delivered(self):
        # Task 3.9's rule, against the slot directly. It is the rule that
        # stops a finished script steering a goal it never ran for. NOTE: a
        # ticking script currently carries no goal id (a held script does not
        # tick), so this cannot yet fire in production -- the rule is pinned
        # here so it is correct when identity reaches the store.
        # KILLS: delivering a pending result regardless of which goal it named.
        slot = self.a._result_slot
        slot.store("goal-A", {"text": "found it"}, "done")
        allowed, reason = slot.may_call(goal_id="goal-B")
        self.assertFalse(allowed)
        self.assertEqual(reason, "goal-changed")

    # -- 3.5 / 3.6: turning a pending result into exactly one call -----
    def test_a_pending_result_starts_one_planner_call_carrying_the_result(self):
        # KILLS: parking the result and never delivering it -- the defect the
        # lead found in the design, where a done script's result only reached
        # the planner if a player happened to speak.
        #
        # Trigger `escalate`: a `done` result closes its goal instead (see
        # `test_a_done_result_closes_its_goal_without_a_planner_call`).
        self.a._plan_steps = []
        self.a._result_slot.store("", {"text": "a red flower"}, "escalate")
        with mock.patch.object(self.agent_mod.threading, "Thread") as Thread:
            with mock.patch("builtins.print"):
                self.a._maybe_plan_on_result()
        Thread.assert_called_once()
        args = Thread.call_args.kwargs["args"]
        self.assertIn("a red flower", args[0],
                      "the result must reach the planner prompt, not just the log")
        self.assertFalse(self.a._result_slot.has_pending(),
                         "a delivered result must be consumed, not re-delivered")

    def test_a_done_result_closes_its_goal_without_a_planner_call(self):
        # The lead's issue 2 (03:22Z): a done result was fed to the
        # orchestrator as a new task, the planner decomposed "Script result
        # (done): ..." and declined with a clarify question, asking the player
        # whether there was a new task.
        #
        # KILLS: handing a done result to `_plan_with_result`.
        self.a._plan_steps = []
        self.a._active_goal_id = "goal-A"
        self.a._result_slot.store("goal-A", {"text": "mined 3 dirt"}, "done")
        self.a._unbind_planner_script = mock.Mock(return_value=True)
        with mock.patch.object(self.agent_mod.threading, "Thread") as Thread:
            with mock.patch("builtins.print"), \
                 mock.patch.object(self.agent_mod.api, "system_chat") as chat:
                self.a._maybe_plan_on_result()
        Thread.assert_not_called()
        chat.assert_called_once()
        self.assertIn("mined 3 dirt", str(chat.call_args),
                      "closing must report the outcome to the player")
        self.assertFalse(self.a._result_slot.has_pending(),
                         "a closed goal leaves no pending result")
        self.assertEqual(self.a._active_goal_id, "",
                         "the closed goal must not outlive its close")
        self.a._unbind_planner_script.assert_called_once()

    def test_a_done_result_closes_even_during_a_planner_cooldown(self):
        # Closing makes no planner call, so the planner-call caps must not
        # hold it: a finished goal must not stay open until a 15-minute
        # cooldown expires. The caps exist to bound LLM calls, not to delay
        # a result the player is waiting on.
        #
        # KILLS: checking `may_call` before the done branch.
        slot = self.a._result_slot
        slot._cooldown = 3600              # would hold any delivery
        self.a._plan_steps = []
        self.a._active_goal_id = "goal-A"
        slot.store("goal-A", {"text": "mined 3 dirt"}, "done")
        self.a._unbind_planner_script = mock.Mock(return_value=True)
        with mock.patch.object(self.agent_mod.threading, "Thread") as Thread:
            with mock.patch("builtins.print"), \
                 mock.patch.object(self.agent_mod.api, "system_chat"):
                self.a._maybe_plan_on_result()
        Thread.assert_not_called()
        self.assertFalse(slot.has_pending())

    def test_a_done_result_for_a_superseded_goal_does_not_close_the_current_one(self):
        # Identity is checked before the trigger: a stale done result must not
        # close a goal it never ran for.
        #
        # KILLS: closing on `trigger == "done"` without comparing goals.
        self.a._plan_steps = []
        self.a._active_goal_id = "goal-B"
        self.a._result_slot.store("goal-A", {"text": "stale"}, "done")
        self.a._unbind_planner_script = mock.Mock(return_value=True)
        with mock.patch.object(self.agent_mod.threading, "Thread") as Thread:
            with mock.patch("builtins.print"), \
                 mock.patch.object(self.agent_mod.api, "system_chat") as chat:
                self.a._maybe_plan_on_result()
        Thread.assert_not_called()
        chat.assert_not_called()
        self.assertEqual(self.a._active_goal_id, "goal-B",
                         "goal B was running and must survive A's stale result")
        self.a._unbind_planner_script.assert_not_called()

    def test_no_pending_result_makes_no_call(self):
        # The property: a pass with nothing pending starts no call.
        #
        # NOTE (measured, 2026-11-22): the `has_pending` guard is NO LONGER
        # redundant. It used to be, because `may_call`'s `no-result` branch
        # caught the empty slot. The done-close change reads `slot.peek()`
        # before `may_call`, so removing the guard raises TypeError on a None
        # unpack -- this test errors, it does not merely fail. The guard is
        # the enforcement, not defence in depth.
        self.a._plan_steps = []
        with mock.patch.object(self.agent_mod.threading, "Thread") as Thread:
            self.a._maybe_plan_on_result()
        Thread.assert_not_called()

    def _run_pass(self, new_msgs):
        """One loop pass' planner branch, as the loop (:3521) has it.

        The REAL `_run_planner_for_pass`, `_maybe_plan` and
        `_maybe_plan_on_result` are used, so a
        change to either reds these tests. Two fakes sit below them, in
        threaded things only: the planner's Thread, whose start calls
        `_run_orchestrator`, and the HTTP api. So "a call started, with what
        text" is read off the hand-off between the two, not from the thread
        body. The local `planner.decompose` is faked so a planner path may
        finish; it starts no thread, so it shows up as no hand-off.
        """
        # The pass reaches the legacy planner branch (agent.py:938-939) after
        # the hand-off, so the planner itself is faked and only that hand-off
        # -- `Thread` made with the task -- is real and recorded.
        self.a.model = "test-model"
        self.a._get_my_inventory_summary = lambda: ""
        with mock.patch.object(self.agent_mod, "planner") as planner:
            class Answer(list):
                script = None   # no program: the step list is what follows
            planner.decompose.return_value = Answer(["look around"])
            return self._pass_body(new_msgs)

    def _pass_body(self, new_msgs):
        # Read by `_maybe_plan`: the task board (agent.py:568) and
        # consuming the message (agent.py:517).
        self.a._current_task_id = None
        self.a.chat_history = []
        self.a._following_player = None
        # Read by `_maybe_plan` (agent.py:675) and by the legacy planner
        # branch (:938), which the shadow plan write also touches.
        self.a.semantic_mem = None
        self.a._cached_inventory = []
        self.a._l4_escalations = 0
        self.a.conversation_history = []
        self.a._shadow_plan_write = mock.Mock()
        self.a._consume_message = mock.Mock()
        # The hand-off into the planner's thread is the thing measured, so it
        # is the one fake: recording `Thread(args=(prompt, role))` where the
        # task is made, instead of starting it.
        prompts = []

        def thread(**kw):
            prompts.append(kw["args"][0])
            return mock.Mock()

        with mock.patch.object(self.agent_mod, "api", mock.Mock()), \
                mock.patch.object(self.agent_mod.threading, "Thread", thread), \
                mock.patch("builtins.print"):
            self.a._run_planner_for_pass(new_msgs)
        return prompts

    def test_a_player_message_wins_the_pass(self):
        # 3.6: a player message wins a pass -- the message reaches L3 and the
        # older result waits for a pass of its own.
        #
        # HONEST LIMIT (measured): this pass shape cannot red the guard. The
        # player's message is not address-parsed (no "#" prefix, so it is not
        # "for you"), so `_maybe_plan` only decomposes it; no thread starts.
        # With the guard inverted (`if True`) the result entry still makes no
        # call, because `_maybe_plan` left a non-empty `_plan_steps` and the
        # entry returns on it. An inverted guard here is undetectable from
        # outside, so this test pins the outcome rather than a mutant: the
        # message is what reached L3, the result is still queued, and no
        # second call was made. The guard's other side is pinned by
        # `test_a_pass_with_no_message_delivers_the_result`.
        self.a._is_chat_message = lambda text: True
        self.a._reply_in_character = mock.Mock()
        self.a._plan_steps = []
        self.a._result_slot = self.agent_mod.ResultSlot()
        self.a._result_slot.store("", {"text": "a red flower"}, "escalate")
        prompts = self._run_pass(["Player: scout the hill"])
        self.assertEqual(prompts, [], "the legacy planner path hands no task "
                                      "to a thread")
        self.assertNotIn("a red flower", self.a._plan_instruction,
                         "the player's message, not the result, reached L3")
        self.assertTrue(self.a._result_slot.has_pending(),
                        "the result waits for a pass of its own")

    def test_a_pass_with_no_message_delivers_the_result(self):
        # The other branch of the same predicate: with no message, the
        # result's call is the one that starts.
        # KILLS: a guard that never lets the result entry run.
        self.a._plan_steps = []
        self.a._result_slot = self.agent_mod.ResultSlot()
        self.a._result_slot.store("", {"text": "a red flower"}, "escalate")
        prompts = self._run_pass([])
        self.assertEqual(len(prompts), 1)
        self.assertIn("a red flower", prompts[0])

    def test_a_pending_result_is_held_off_at_the_hour_cap(self):
        # 3.7: the caps are the guard on result-triggered calls, not a
        # backstop behind a working path. Spend the hour on the real
        # `_maybe_plan_on_result` (cooldown 0, so the hour cap is the bound),
        # then report a fifth time and require the planner call to be
        # suppressed and the result KEPT, with the cap's name logged.
        #
        # KILLS: an `_maybe_plan_on_result` that ignores `may_call`, which
        # calls the planner on the fifth result.
        self.a._plan_steps = []
        self.a._result_slot = self.agent_mod.ResultSlot(
            clock=lambda: 1000.0, cooldown_seconds=0)
        calls = []

        class Thread:
            def __init__(self, **kw):
                calls.append(kw)

            def start(self):
                pass

        with mock.patch.object(self.agent_mod.threading, "Thread", Thread):
            for _ in range(5):
                self.a._result_slot.store("", {"text": "found"}, "escalate")
                with mock.patch("builtins.print") as pr:
                    self.a._maybe_plan_on_result()
        self.assertEqual(len(calls), 4, "four calls an hour, then held")
        self.assertTrue(self.a._result_slot.has_pending(),
                        "the fifth result is queued under the cap, not dropped")
        printed = " ".join(str(c.args[0]) for c in pr.call_args_list)
        self.assertIn("held (hour-cap)", printed)

    def test_a_pending_result_is_held_off_inside_the_cooldown(self):
        # 3.7: with the real 15-minute cooldown, a second result right after
        # a delivered one is held with the cooldown named.
        #
        # KILLS: a version enforcing only the hour cap.
        self.a._plan_steps = []
        now = [1000.0]
        self.a._result_slot = self.agent_mod.ResultSlot(clock=lambda: now[0])
        calls = []

        def thread(**kw):
            calls.append(kw)
            return mock.Mock()

        with mock.patch.object(self.agent_mod.threading, "Thread", thread):
            self.a._result_slot.store("", {"text": "found"}, "escalate")
            with mock.patch("builtins.print"):
                self.a._maybe_plan_on_result()
            self.a._result_slot.store("", {"text": "found again"}, "escalate")
            with mock.patch("builtins.print") as pr:
                self.a._maybe_plan_on_result()
        self.assertEqual(len(calls), 1)
        self.assertTrue(self.a._result_slot.has_pending())
        printed = " ".join(str(c.args[0]) for c in pr.call_args_list)
        self.assertIn("held (cooldown)", printed)

    def test_a_result_arriving_mid_plan_is_queued_not_injected(self):
        # KILLS: starting a second planner while one is live, which would put
        # two planners on one bot. The result must survive the wait.
        self.a._plan_steps = ["step-1"]
        self.a._result_slot.store("", {"text": "x"}, "escalate")
        with mock.patch.object(self.agent_mod.threading, "Thread") as Thread:
            self.a._maybe_plan_on_result()
        Thread.assert_not_called()
        self.assertTrue(self.a._result_slot.has_pending(),
                        "a queued result must stay parked for a later pass")


class NoPlannerPathMintsAGoalIdTest(unittest.TestCase):
    """3.9: the planner never mints a goal id; replace keeps the existing one."""

    def setUp(self):
        agent_mod = _agent_module()
        self.agent_mod = agent_mod
        self.a = agent_mod.BotRunner.__new__(agent_mod.BotRunner)
        # __init__ never ran, so supply the guard it would have created.
        self.a._script_say_guard = agent_mod.ScriptSayGuard()
        self.a.name = "Scout"
        self.a._script_hold_seq = 4
        self.a._script_hold = {"goal_id": "chat:Player:mine#4", "goal_text": "mine"}
        self.a._run_orchestrator = mock.Mock()
        self.a._result_slot = agent_mod.ResultSlot()

    def test_a_result_call_carries_the_existing_goal_and_mints_none(self):
        # The result-triggered call re-enters the orchestrator with the goal
        # the hold names; the sequence counter must not move.
        #
        # KILLS: minting a fresh id for a result-triggered call (a new id
        # whose release could never match the hold, or match a later goal).
        with mock.patch.object(self.agent_mod.threading, "Thread",
                               side_effect=lambda **kw: mock.Mock()) as Thread, \
                mock.patch("builtins.print"):
            self.a._plan_with_result({"text": "x"}, "done", "chat:Player:mine#4")
        kw = Thread.call_args.kwargs
        self.assertEqual(kw["kwargs"]["goal_id"], "chat:Player:mine#4")
        self.assertEqual(self.a._script_hold_seq, 4, "no id was minted")

    def test_a_replace_outcome_keeps_the_goal_id(self):
        # "Replace" (lead's call): a second goal replaces the hold and keeps
        # the id the first one had. The minting function is called by
        # `_maybe_plan` alone, on a player message.
        #
        # KILLS: a replace that mints a new id.
        self.a._begin_script_hold("chat:Player:mine#4", "replace me")
        self.assertEqual(self.a._script_hold["goal_id"], "chat:Player:mine#4")
        self.assertEqual(self.a._script_hold_seq, 4)


class PlannerForPassHonoursTheCapsTest(unittest.TestCase):
    """`_run_planner_for_pass` must enforce all three (F-1).

    The reviewer deleted the goal id from the delivery record and 81 tests
    stayed green, because every earlier test checked the slot's predicate or
    the individual helpers and none drove the entry the loop actually calls.
    This drives `_run_planner_for_pass` itself with an injected clock, and
    reads the goal off the boundary that consumes it: `_run_orchestrator`'s
    `goal_id`, whose only use is `_end_script_hold(goal_id or None)`.
    """

    def setUp(self):
        agent_mod = _agent_module()
        self.agent_mod = agent_mod
        self.now = [1000.0]
        self.a = agent_mod.BotRunner.__new__(agent_mod.BotRunner)
        # __init__ never ran, so supply the guard it would have created.
        self.a._script_say_guard = agent_mod.ScriptSayGuard()
        self.a._lock = threading.Lock()
        self.a.name = "Scout"
        self.a.profile = {}
        self.a._plan_steps = []
        self.a._plan_instruction = ""
        self.a._result_slot = agent_mod.ResultSlot(clock=lambda: self.now[0])
        self.a._script_hold = None
        self.a._maybe_plan = mock.Mock()
        self.plan_calls = []

        def fake_orchestrator(task_text, sender="", order_id="",
                              order_kind="", goal_id=""):
            self.plan_calls.append({"text": task_text, "goal_id": goal_id})
            # A real run finishes and `_maybe_plan_on_result` refuses only
            # while `_plan_steps` is non-empty, so leave it empty for the
            # next pass; otherwise the cap is never reached in this fixture.
            self.a._plan_steps = []

        self.a._run_orchestrator = fake_orchestrator

    def _bot(self, name, calls):
        """A second bot on the SAME clock, with its own slot and its own calls."""
        b = self.agent_mod.BotRunner.__new__(self.agent_mod.BotRunner)
        # __init__ never ran, so supply the guard it would have created.
        b._script_say_guard = self.agent_mod.ScriptSayGuard()
        b._lock = threading.Lock()
        b.name = name
        b.profile = {}
        b._plan_steps = []
        b._plan_instruction = ""
        b._result_slot = self.agent_mod.ResultSlot(clock=lambda: self.now[0])
        b._script_hold = None
        b._maybe_plan = mock.Mock()
        b._run_orchestrator = lambda *a, **k: calls.append(a[0])
        return b

    def _pass(self, value="a red flower", goal_id=""):
        """One pass with no message and `value` pending. Returns True if it planned.

        Trigger `escalate`, not `done`: a `done` result now CLOSES its goal
        without a planner call, so it would never reach the caps these tests
        measure. `escalate` is the delivery path that still plans.
        """
        self.a._result_slot.store(goal_id, {"text": value, "truncated": False}, "escalate")
        before = len(self.plan_calls)
        with mock.patch("builtins.print"):
            self.a._run_planner_for_pass([])
        return len(self.plan_calls) > before

    def test_the_four_a_hour_cap_turns_it_red(self):
        # KILLS: dropping `slot.record_call()` from the delivery -- then every
        # pass plans, so the fifth call of the hour happens.
        #
        # The constant is NOT free: it must exceed the 900s cooldown.
        from result_delivery import COOLDOWN_SECONDS
        # Exact relationship, not a loose bound: cooldown * (cap) == hour, so
        # the cooldown alone already holds the rate to 4/hour and the cap can
        # only bite on the boundary. Change any of the three and the reasoning
        # below is void -- so this fails loudly.
        from result_delivery import HOUR_SECONDS, MAX_RESULTS_PER_HOUR
        self.assertEqual(COOLDOWN_SECONDS * MAX_RESULTS_PER_HOUR,
                         HOUR_SECONDS,
                         "4 gaps of cooldown exactly span the hour only at "
                         "900s * 4; the reachability note below depends on it")
        # Five calls inside one rolling hour is IMPOSSIBLE while the cooldown
        # is strict at 900s: the 2nd..5th each wait >= 900s after the previous,
        # so the 5th is >= 4*900 = 3600s after the 1st and the 1st has rolled
        # out of the window. So the cap is reachable only when the cooldown is
        # removed or shortened -- and this test pins exactly that: with the
        # cooldown lifted, the 5th call in one hour is refused BY THE CAP.
        slot = self.a._result_slot
        slot._cooldown = 0                  # the cap must stand on its own
        self.assertTrue(self._pass("r1"))
        for n in (2, 3, 4):
            self.now[0] += 60               # well inside the hour
            self.assertTrue(self._pass(f"r{n}"))
        self.now[0] += 60
        self.assertFalse(self._pass("r5"),
                         f"a fifth call in one hour must be refused: "
                         f"{[c['text'] for c in self.plan_calls]!r}")
        self.assertEqual(len(self.plan_calls), 4,
                         f"calls: {[c['text'] for c in self.plan_calls]!r}")

    def test_the_fifteen_minute_cooldown_turns_it_red(self):
        # KILLS: making `may_call` ignore `_recent_calls` -- then the second
        # result one minute later plans immediately.
        self.assertTrue(self._pass("r1"))
        self.now[0] += 60
        self.assertFalse(self._pass("r2"),
                         f"a call one minute after the last must be held: "
                         f"{[c['text'] for c in self.plan_calls]!r}")
        self.now[0] += 15 * 60
        self.assertTrue(self._pass("r3"),
                        "the call must resume once the cooldown has expired")

    def test_the_goal_the_delivery_is_attributed_to_turns_it_red(self):
        # KILLS: passing a constant or empty goal_id to `_plan_with_result` --
        # the reviewer's exact deletion, which left 81 tests green.
        #
        # The hold is the fallback that names the goal when no active id is
        # set (a goal that never reached the orchestrator); the active id is
        # the primary record and is covered separately.
        self.a._active_goal_id = ""
        self.a._script_hold = {"goal_id": "goal-A", "goal_text": "t"}
        self.assertTrue(self._pass(goal_id="goal-A"))
        self.assertEqual(self.plan_calls[0]["goal_id"], "goal-A",
                         f"the planner call must carry the held goal: "
                         f"{self.plan_calls!r}")
        self.assertIn("Script result (escalate)", self.plan_calls[0]["text"])
        self.assertIn("a red flower", self.plan_calls[0]["text"])


    def test_two_bots_each_get_a_call_inside_the_same_15_minutes(self):
        # F-5. The scenario "the cooldown is per bot, not per script" could not
        # fail: a cooldown keyed BY SCRIPT gave zero reds across 84 tests,
        # because no test ever had a second bot. Two real BotRunners, each with
        # its own ResultSlot, both driven through _run_planner_for_pass on one
        # shared clock.
        #
        # KILLS (needs both bots to exist):
        #  - a cooldown keyed by script name: both bots run the same script, so
        #    the second is wrongly held;
        #  - a slot shared at module level: the second bot's result overwrites
        #    or is refused by the first bot's call.
        calls_b, calls_c = [], []
        b = self._bot("B", calls_b)
        c = self._bot("C", calls_c)

        def one_pass(bot):
            bot._result_slot.store("", {"text": "r", "truncated": False}, "escalate")
            with mock.patch("builtins.print"):
                bot._run_planner_for_pass([])

        one_pass(b)
        self.now[0] += 60                # one minute later, well inside 15 min
        one_pass(c)

        self.assertEqual(len(calls_b), 1, f"bot B: {calls_b!r}")
        self.assertEqual(len(calls_c), 1,
                         f"the second bot must not be held by the first "
                         f"bot's cooldown: {calls_c!r}")

    def test_the_reason_names_the_cooldown_when_both_bounds_refuse(self):
        # F-6. The cap alone cannot be reached at a 900s cooldown, so when
        # both would refuse the real reason is the cooldown. Naming the cap
        # there put 424 of 466 of the reviewer's refusals on the wrong reason.
        slot = self.a._result_slot
        slot.store("", {"text": "r", "truncated": False}, "escalate")
        slot._call_times = [self.now[0] - 60] * 4   # 4 calls, newest 60s ago
        allowed, reason = slot.may_call(goal_id="")
        self.assertFalse(allowed)
        self.assertEqual(reason, "cooldown",
                         "both bounds refuse; the binding one must be named")

    def test_the_reason_still_names_the_cap_when_only_the_cap_refuses(self):
        # The other half: with the cooldown satisfied, a fifth call is still
        # named "hour-cap". Without this, "always return cooldown" would pass
        # the test above.
        slot = self.a._result_slot
        slot.store("", {"text": "r", "truncated": False}, "escalate")
        slot._call_times = [self.now[0] - 1800] * 4  # 4 calls, newest 30m ago
        allowed, reason = slot.may_call(goal_id="")
        self.assertFalse(allowed)
        self.assertEqual(reason, "hour-cap")



class BoundScriptSourceIsLoggedTest(unittest.TestCase):
    """Task 4.5 ask 2: a bound planner script's source is logged once.

    Trial 4.1 could not be diagnosed: a script reported "no shears" while the
    bot held shears, and no log recorded what the script had been given. These
    pin the three things that make such a line useful rather than misleading:
    it carries an identity (hash) and the bot, it is clipped WITH a marker so a
    short script is not confused with a clipped one, and it never echoes a
    hand-written binding's file.
    """

    def setUp(self):
        agent_mod = _agent_module()
        self.agent_mod = agent_mod
        self.a = agent_mod.BotRunner.__new__(agent_mod.BotRunner)
        self.a._script_say_guard = agent_mod.ScriptSayGuard()
        self.a._lock = threading.Lock()
        self.a.name = "Scout"
        self.a.profile = {}
        self.a._script_tick = None
        self.a._script_loaded = False
        self.a._script_hold = None
        self.a._script_hold_seq = 0
        self.a._planner_script = None

    def _bind_and_capture(self, src, hand_written=False):
        import contextlib, io
        buf = io.StringIO()
        path = "/bot/scripts/scout.js" if hand_written else None
        with mock.patch.object(self.a, "_dry_tick", return_value=True), \
             mock.patch.object(self.a, "_bound_script_path", return_value=path), \
             contextlib.redirect_stdout(buf):
            ok = self.a._bind_planner_script(src)
        return ok, buf.getvalue()

    def test_the_source_is_logged_with_bot_and_hash(self):
        # KILLS: binding silently, which is exactly what made trial 4.1
        # un-diagnosable -- nothing recorded the script that ran.
        src = "const s = look.inventory(); api.say(s.items[0].item);"
        ok, out = self._bind_and_capture(src)
        self.assertTrue(ok)
        self.assertIn("planner script source", out)
        self.assertIn("Scout", out)
        digest = self.agent_mod._script_digest(src)
        self.assertIn(digest, out, f"the hash must identify the source; got:\n{out}")
        self.assertIn("s.items[0].item", out, "the source itself must be readable")

    def test_a_long_script_is_clipped_and_says_so(self):
        # KILLS: a silent cut, which makes a clipped script look complete.
        src = "// pad\n" * 2000
        self.assertGreater(len(src.encode()), self.agent_mod.SCRIPT_LOG_CAP)
        ok, out = self._bind_and_capture(src)
        self.assertTrue(ok)
        self.assertIn("truncated at bind", out)
        self.assertLess(len(out.encode()), self.agent_mod.SCRIPT_LOG_CAP + 600,
                        "the log line must stay near the cap, not echo 64 KiB")

    def test_a_short_script_carries_no_truncation_marker(self):
        # The complement: the marker must mean something. If it appeared on a
        # short script a reader could not tell clipped from complete.
        ok, out = self._bind_and_capture("api.say('hi');")
        self.assertTrue(ok)
        self.assertNotIn("truncated at bind", out)

    def test_a_hand_written_binding_is_not_echoed(self):
        # KILLS: logging a human's file, which the spec forbids -- bindings.json
        # is the record a person already keeps.
        src = "// human script\napi.say('mine');"
        ok, out = self._bind_and_capture(src, hand_written=True)
        self.assertFalse(ok, "a hand-written binding must win and bind nothing")
        self.assertNotIn("planner script source", out)
        self.assertNotIn("human script", out)

class ScriptSpinTest(unittest.TestCase):
    """Spec, "A Repeatedly Completed Identical Action Yields The Goal".

    The identical completed action is the signal, not a world-state diff:
    position and ages move every tick for reasons unrelated to the action, so a
    diff would fire on a slow action or stay silent on a spin. Trial 4.3
    (2026-11-22, bot Axiom) re-sent one GOTO 10+ times, each COMPLETED.
    """

    def setUp(self):
        agent_mod = _agent_module()
        self.agent_mod = agent_mod
        self.a = agent_mod.BotRunner.__new__(agent_mod.BotRunner)
        self.a._lock = threading.Lock()
        self.a.name = "Scout"
        self.a.profile = {}
        self.a._script_tick = None
        self.a._script_say_guard = agent_mod.ScriptSayGuard()
        self.a._script_loaded = True
        self.a._l3_orchestrator_dispatch = mock.Mock(return_value="COMPLETED GOTO ok")
        self.a._unbind_planner_script = mock.Mock(return_value=True)
        self.a._resubmit_yielded_goal = mock.Mock(return_value=True)
        self.a._script_repeat_key = None
        self.a._script_repeat_count = 0
        self.a._active_goal_id = "goal-A"
        self.a._active_goal_text = "walk to the cache"
        self.a._script_hold = None
        self.a._plan_instruction = ""

    def _run_identically(self, n, act=None):
        """Run n ticks whose single action is identical and COMPLETES."""
        act = act or {"kind": "GOTO", "x": "-15", "y": "77", "z": "-28"}

        class Stub:
            def tick(_self):
                return (True, [dict(act)], [], "ok")

        self.a._script_tick = Stub()
        results = []
        with mock.patch("builtins.print"):
            for _ in range(n):
                results.append(self.a._run_script_tick())
        return results

    def test_trial_4_3_identical_goto_yields_at_the_bound(self):
        # KILLS: never yielding on a spin (the shipped behaviour that needed a
        # human restart).
        results = self._run_identically(self.agent_mod.SCRIPT_REPEAT_MAX)
        # Every tick up to and including the Nth ran the action.
        self.assertTrue(all(results), results)
        self.a._unbind_planner_script.assert_called_once()
        self.a._resubmit_yielded_goal.assert_called_once()
        self.assertEqual(self.a._resubmit_yielded_goal.call_args[0][0], "goal-A",
                         "the ACTIVE goal must be the one re-submitted")

    def test_it_does_not_yield_before_the_bound(self):
        # KILLS: yielding one tick early, which would break a slow but correct
        # movement by re-planning it away.
        results = self._run_identically(self.agent_mod.SCRIPT_REPEAT_MAX - 1)
        self.assertTrue(all(results), results)
        self.a._unbind_planner_script.assert_not_called()

    def test_a_different_kind_resets_the_count(self):
        # KILLS: keying the run on anything coarser than the whole action (e.g.
        # "how many ticks ran", or ignoring the kind). A script alternating
        # GOTO and MINE is making progress; if the key missed the action it
        # would be yielded as a spin and lose its goal mid-job.
        self._run_identically(self.agent_mod.SCRIPT_REPEAT_MAX - 1)
        results = self._run_identically(1, {"kind": "MINE", "target": "dirt"})
        self.assertTrue(results[0])
        self.a._unbind_planner_script.assert_not_called()
        self.assertEqual(getattr(self.a, "_script_repeat_count", 1), 1,
                         "a different KIND must start a new run")

    def test_a_different_coordinate_is_a_different_action(self):
        # KILLS: keying only on the kind. A bot patrolling between waypoints
        # re-issues GOTO with new coordinates each time; that is progress and
        # must not be yielded.
        self._run_identically(self.agent_mod.SCRIPT_REPEAT_MAX - 1)
        results = self._run_identically(1, {"kind": "GOTO", "x": "9", "y": "2", "z": "3"})
        self.assertTrue(results[0])
        self.a._unbind_planner_script.assert_not_called()

    def test_a_two_action_tick_is_never_a_spin(self):
        # KILLS: treating "the same action appears among several" as a loop.
        # A tick that ran more than one distinct action is progress.
        acts = [{"kind": "GOTO", "x": "1", "y": "2", "z": "3"},
                {"kind": "MINE", "target": "dirt"}]

        class Stub:
            def tick(_self):
                return (True, [dict(x) for x in acts], [], "ok")

        self.a._script_tick = Stub()
        with mock.patch("builtins.print"):
            for _ in range(self.agent_mod.SCRIPT_REPEAT_MAX + 2):
                self.assertTrue(self.a._run_script_tick())
        self.a._unbind_planner_script.assert_not_called()

    def test_the_spin_yield_logs_the_action_and_the_count(self):
        self._run_identically(self.agent_mod.SCRIPT_REPEAT_MAX)
        # The yield message names the cause; capture the prints to prove the
        # operator can tell a spin yield from an all-refused one. _run_identically
        # patches print itself, so drive the ticks here rather than nesting a
        # second patch over it -- an inner patch would swallow every call and
        # make this assertion read an empty string.
        self.a._unbind_planner_script.reset_mock()
        act = {"kind": "GOTO", "x": "-15", "y": "77", "z": "-28"}

        class Stub:
            def tick(_self):
                return (True, [dict(act)], [], "ok")

        self.a._script_tick = Stub()
        with mock.patch("builtins.print") as pr:
            for _ in range(self.agent_mod.SCRIPT_REPEAT_MAX):
                self.a._run_script_tick()
        text = " ".join(str(c) for c in pr.call_args_list)
        self.assertIn("spin", text)
        self.assertIn(str(self.agent_mod.SCRIPT_REPEAT_MAX), text)


class ScriptSurfaceNamesSelfTest(unittest.TestCase):

    def test_the_prompt_names_look_self_and_its_fields(self):
        # Spec, "The prompt names look.self and its fields". Trial 4.3's
        # planner guessed snapshot.self.position because no self lookup was
        # documented; the fix must be visible where a planner reads.
        import planner
        src = planner.SCRIPT_SURFACE
        self.assertIn("look.self()", src)
        self.assertIn("health", src)
        self.assertIn("food", src)
        self.assertIn("snapshot.self", src,
                      "the surface must warn against the path the trial guessed")


if __name__ == "__main__":
    unittest.main(verbosity=2)

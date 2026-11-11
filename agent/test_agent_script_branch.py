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
        self.a.name = "Scout"
        self.a.profile = {}
        self.a._script_tick = None
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


if __name__ == "__main__":
    unittest.main(verbosity=2)

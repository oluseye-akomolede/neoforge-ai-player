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
import os
import sys
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
        self._with_tick((True, [{"directive": {"type": "STORE_ALL"}}], [], "ok"))
        self.assertTrue(self.a._run_script_tick(),
                        "a handled tick must tell the loop to skip the planner")
        self.a._run_directive.assert_called_once_with({"type": "STORE_ALL"})

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
                self.a._run_directive.reset_mock()
                self._with_tick(result)
                self.assertFalse(self.a._run_script_tick(),
                                 f"{label} suppressed the planner")
                self.a._run_directive.assert_not_called()

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


if __name__ == "__main__":
    unittest.main(verbosity=2)

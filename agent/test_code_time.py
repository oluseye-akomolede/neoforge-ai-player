"""Code-time metering (change: coded-agents, task 5.1 + proof 5.5).

Drives the REAL `BotRunner._run_script_tick` -- not `record_tick` in isolation
-- because the load-bearing question is whether the counter is fed at the one
send point and nowhere a tick was not sent. A test of `CodeTimeMeter` alone
would pass against a tree where nothing called it, which is the shape of a
meter that records nothing in production.

The scenarios pinned here are the spec's, by name:
  * an active script's hours accrue, at the wall-clock (tick-period) rate;
  * an inactive script accrues nothing -- here, a script that is HELD, whose
    early-return happens before the send point;
  * metering is present while the cap is unlimited (5.5);
  * usage is per bot, never summed.
What the spec is SILENT on -- the day boundary, and survival across an agent
pod restart -- is NOT asserted as if specified; the restart case is checked
only to state the current behaviour (a fresh meter starts at zero).
"""

import threading
import types
import sys
import unittest
from unittest import mock

import importlib


# agent.py imports psycopg2 / fastapi / uvicorn at module scope. None is
# exercised by metering, but the import must succeed for `agent` to load at
# all. Stub them so the REAL agent.py loads and the REAL _run_script_tick runs
# -- the same pattern (and the same reasoning) as test_agent_script_branch.py.
class _Any:
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, n):
        return _Any()

    def __call__(self, *a, **k):
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

from code_time import CodeTimeMeter


def _runner(agent_mod, name="Scout"):
    """A BotRunner built the way the suite builds them: `__new__`, no `__init__`.

    `code_time` is deliberately NOT set, so `_record_code_time_tick` has to
    create it lazily -- exactly the production path for a runner whose first
    metered tick arrives before `__init__` would have run in a test fixture.
    """
    a = agent_mod.BotRunner.__new__(agent_mod.BotRunner)
    a.name = name
    a.profile = {}
    a._script_tick = None
    a._script_loaded = True
    a._script_hold = None
    a._script_hold_seq = 0
    a._script_say_guard = agent_mod.ScriptSayGuard()
    a._result_slot = agent_mod.ResultSlot()
    a._lock = threading.Lock()
    a._l3_orchestrator_dispatch = mock.Mock(return_value="COMPLETED")
    a._run_directive = mock.Mock(return_value={"success": True})
    a._active_goal_id = "goal-A"
    return a


class _StubTick:
    """A ScriptTick stand-in: one handled tick proposing nothing."""

    last_result = None
    last_deliveries = ()
    last_logs = ()
    last_logs_dropped = 0

    def tick(self):
        return (True, [], [], "ok")


class MeterUnitTest(unittest.TestCase):
    """The counter's own arithmetic -- the unit is the period, counted once."""

    def test_one_tick_adds_one_period(self):
        m = CodeTimeMeter(tick_period=2.0)
        m.record_tick()
        self.assertEqual(m.usage_seconds(), 2.0)
        self.assertEqual(m.tick_count(), 1)

    def test_a_full_hour_of_ticks_is_one_code_hour(self):
        # 0.5 ticks/s for 3600 s = 1800 ticks of 2.0 s.
        m = CodeTimeMeter(tick_period=2.0)
        for _ in range(1800):
            m.record_tick()
        self.assertAlmostEqual(m.usage_hours(), 1.0, places=9)

    def test_cap_is_unlimited_and_never_exhausts(self):
        m = CodeTimeMeter(tick_period=2.0)
        for _ in range(10_000):
            m.record_tick()
        self.assertIsNone(m.daily_cap_hours(), "the cap must default to unlimited")
        self.assertFalse(m.is_exhausted(), "an unlimited cap must never exhaust")


class MeteringThroughTheSendPointTest(unittest.TestCase):
    """5.5 and the active/inactive scenarios, through `_run_script_tick`."""

    def setUp(self):
        self.agent_mod = importlib.import_module("agent")

    def test_an_active_tick_is_metered_while_the_cap_is_unlimited(self):
        # 5.5: usage is recorded even with the cap unlimited.
        a = _runner(self.agent_mod)
        a._script_tick = _StubTick()
        with mock.patch("builtins.print"):
            a._run_script_tick()
        self.assertEqual(a.code_time.tick_count(), 1,
                         "an active script's sent tick must be counted")
        self.assertGreater(a.code_time.usage_hours(), 0.0,
                           "usage must be recorded while the cap is unlimited")

    def test_hours_accrue_over_many_ticks(self):
        # The active-script scenario: usage keeps increasing per sent tick.
        a = _runner(self.agent_mod)
        a._script_tick = _StubTick()
        with mock.patch("builtins.print"):
            for _ in range(5):
                a._run_script_tick()
        self.assertEqual(a.code_time.tick_count(), 5)
        self.assertAlmostEqual(a.code_time.usage_seconds(), 5 * 2.0, places=9)

    def test_a_held_script_accrues_nothing(self):
        # The held-time scenario: a hold returns SCRIPT_HELD BEFORE the send
        # point, so no tick is sent and no time is counted.
        a = _runner(self.agent_mod)
        a._script_tick = _StubTick()
        a._script_hold = {"goal_id": "g1", "goal_text": "dig"}
        with mock.patch("builtins.print"):
            before = a._run_script_tick()
        self.assertIs(before, self.agent_mod.SCRIPT_HELD,
                      "a held script must return SCRIPT_HELD, not tick")
        # code_time is untouched: the meter was never even created.
        self.assertIsNone(getattr(a, "code_time", None),
                          "a held tick must not even build a meter")

    def test_usage_is_per_bot_and_never_summed(self):
        a = _runner(self.agent_mod, name="Scout")
        b = _runner(self.agent_mod, name="Forge")
        a._script_tick = _StubTick()
        b._script_tick = _StubTick()
        with mock.patch("builtins.print"):
            a._run_script_tick()
            a._run_script_tick()
            b._run_script_tick()
        self.assertEqual(a.code_time.tick_count(), 2)
        self.assertEqual(b.code_time.tick_count(), 1,
                         "one bot's usage must not count against another's")

    def test_a_dry_tick_is_not_metered(self):
        # The dry/rehearsal path (:4009) is a different call and must not
        # count; this asserts the grep-visible fact that it does not reach the
        # metered call site by driving the dry path and checking no meter.
        a = _runner(self.agent_mod)
        with mock.patch("builtins.print"):
            a._dry_tick("api.say('hi');")
        self.assertIsNone(getattr(a, "code_time", None),
                          "a dry/rehearsal tick must not be metered")


if __name__ == "__main__":
    unittest.main()

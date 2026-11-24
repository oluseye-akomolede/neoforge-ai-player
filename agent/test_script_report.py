"""coded-agents task 5.6: the agent side of the report channel.

Drives the REAL `BotRunner._run_script_tick` and the REAL `ScriptTick` shape
where it can, so the seam that decides "is a report due" is the production one,
not a re-implementation in the test.

What is asserted, and why each one matters:

  * cadence: unchanged values are re-sent every REPORT_INTERVAL, because the mod
    ages a report to `stale` after 3 intervals -- a silent-but-healthy agent
    must keep reporting or it looks dead.
  * on-change: a state change is sent immediately, not at the next interval,
    so a player does not wait up to 15 s to see a fallback.
  * no queuing: a failed post sends nothing later. A backlog replayed after an
    outage would present old values as current.
  * previous_code_hours: absent on a bot's first report and absent on a RISE;
    present only when the figure fell. That is the mechanism the design relies
    on to make a fall readable from one report under latest-only storage.
  * the body size, measured from the real serialiser on a named payload -- the
    design says this number was not reproducible when quoted from memory.
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
# REAL agent.py loads -- copied verbatim from test_agent_script_branch.py, the
# established pattern in this suite.
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

import script_report as sr


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class Recorder:
    """A poster that records every body and can be told to fail."""

    def __init__(self):
        self.sent = []
        self.fail = False

    def __call__(self, name, body):
        if self.fail:
            raise OSError("mod unreachable")
        self.sent.append((name, dict(body)))


class ReportSenderCadenceTest(unittest.TestCase):

    def setUp(self):
        self.clock = FakeClock()
        self.rec = Recorder()
        self.sender = sr.ReportSender(self.rec, clock=self.clock)

    def _one(self, **kw):
        defaults = dict(name="Scout", state="script", code_hours=1.0,
                        ticks=100, observed_at="2026-11-24T04:20:00Z",
                        revision="sha256:abc", now=self.clock())
        defaults.update(kw)
        return self.sender.report(**defaults)

    def test_first_report_is_sent(self):
        self.assertTrue(self._one())
        self.assertEqual(len(self.rec.sent), 1)

    def test_unchanged_values_resend_after_the_interval(self):
        self._one()
        # 1 s later: not due, nothing sent.
        self.clock.advance(1.0)
        self.assertFalse(self._one())
        self.assertEqual(len(self.rec.sent), 1, "sent before the interval")
        # Past the interval: due again, even though nothing changed, because
        # the mod ages a silent report to stale.
        self.clock.advance(sr.REPORT_INTERVAL)
        self.assertTrue(self._one())
        self.assertEqual(len(self.rec.sent), 2)

    def test_a_state_change_is_sent_immediately(self):
        self._one(state="script")
        self.clock.advance(0.5)          # well inside the interval
        self.assertTrue(self._one(state="fallback_timeout"))
        self.assertEqual(len(self.rec.sent), 2)
        self.assertEqual(self.rec.sent[1][1]["script_state"], "fallback_timeout")

    def test_a_usage_change_is_sent_immediately(self):
        self._one(code_hours=1.0)
        self.clock.advance(0.5)
        self.assertTrue(self._one(code_hours=1.1, ticks=110))
        self.assertEqual(len(self.rec.sent), 2)

    def test_one_bot_changing_does_not_suppress_another(self):
        self._one(name="Scout")
        self.assertTrue(self._one(name="Digger"))
        self.assertEqual([n for n, _ in self.rec.sent], ["Scout", "Digger"])

    def test_a_failed_post_is_not_queued_or_replayed(self):
        # This is the "never queued" rule. A drop must send nothing later: the
        # next interval sends CURRENT values, not the value that failed.
        self.rec.fail = True
        self.assertFalse(self._one(code_hours=1.0))
        self.assertEqual(self.rec.sent, [])
        self.assertEqual(self.sender.dropped, 1)
        # Recover, and advance past the interval with a NEWER figure.
        self.rec.fail = False
        self.clock.advance(sr.REPORT_INTERVAL)
        self.assertTrue(self._one(code_hours=1.5, ticks=150))
        self.assertEqual(len(self.rec.sent), 1, "the backlog was replayed")
        self.assertEqual(self.rec.sent[0][1]["code_hours"], 1.5,
                         "sent a stale value rather than the current one")

    def test_a_failed_post_is_not_recorded_as_sent(self):
        self.rec.fail = True
        self._one()
        self.assertIsNone(self.sender.last_sent("Scout"),
                          "a failed report was recorded as sent")


class PreviousCodeHoursTest(unittest.TestCase):
    """The design's one mechanism for making a fall readable from one report."""

    def setUp(self):
        self.clock = FakeClock()
        self.rec = Recorder()
        self.sender = sr.ReportSender(self.rec, clock=self.clock)

    def _one(self, hours):
        self.sender.report("Scout", "script", hours, int(hours * 1800),
                           "2026-11-24T04:20:00Z", "sha256:abc",
                           now=self.clock())
        return self.rec.sent[-1][1]

    def test_absent_on_the_first_report(self):
        body = self._one(1.0)
        self.assertNotIn("previous_code_hours", body,
                         "a first report claims a previous figure it has not got")

    def test_absent_on_a_rise(self):
        self._one(1.0)
        self.clock.advance(1.0)
        body = self._one(1.5)
        self.assertNotIn("previous_code_hours", body,
                         "a rise carried a 'previous' figure, which would be "
                         "misread as a fall at a day boundary")

    def test_present_on_a_fall(self):
        self._one(1.5)
        self.clock.advance(1.0)
        body = self._one(0.2)
        self.assertEqual(body["previous_code_hours"], 1.5)
        self.assertEqual(body["code_hours"], 0.2)

    def test_present_again_on_a_second_fall(self):
        self._one(2.0)
        self.clock.advance(1.0)
        self._one(1.0)
        self.clock.advance(1.0)
        body = self._one(0.5)
        self.assertEqual(body["previous_code_hours"], 1.0,
                         "compared against a stale figure rather than the last "
                         "one actually sent")

    def test_absent_means_absent_not_null(self):
        body = self._one(1.0)
        self.assertNotIn("previous_code_hours", body)
        self.assertNotIn("previous_code_hours", sr.build_body(
            "Scout", "script", 1.0, None, 100, "t", "r"),
            "build_body emitted null where the design requires absence")


class BodyShapeTest(unittest.TestCase):

    def test_no_secret_and_no_window_claim(self):
        body = sr.build_body("Scout", "script", 1.0, None, 100,
                             "2026-11-24T04:20:00Z", "sha256:abc")
        self.assertEqual(set(body), {"script_state", "code_hours", "ticks",
                                     "observed_at", "revision"},
                         "the payload gained a field the design does not list")

    def test_body_size_measured_from_the_real_serialiser(self):
        """The design says 'about 0.25 KB' and refuses an exact figure.

        This prints (and bounds) the REAL number on a named payload, so the
        number lives next to the sender rather than in a doc nobody can
        reproduce. The bound is deliberately loose: it is a sanity ceiling, not
        a guarantee anyone may build on.
        """
        body = sr.build_body("Scout", "script", 1234567.123456, 1234567.0,
                             999999999, "2026-11-24T04:20:00Z",
                             "sha256:" + "a" * 64)
        size = len(sr.dumps(body).encode("utf-8"))
        print(f"\n[5.6] named payload, all fields at their design caps: "
              f"{size} bytes")
        self.assertLess(size, 512, f"body grew to {size} bytes")


class RunnerSeamTest(unittest.TestCase):
    """The report is driven from the REAL _run_script_tick, not from the test."""

    def setUp(self):
        import agent as agent_mod
        self.agent_mod = agent_mod

    def _runner(self):
        """Built the way this suite builds runners (see test_code_time._runner):
        `__new__`, no `__init__`, with every attribute `_run_script_tick`
        touches set. My first version omitted `_l3_orchestrator_dispatch` and
        the tick then fell through to the planner path and returned False --
        a broken fixture, not a broken seam."""
        a = self.agent_mod.BotRunner.__new__(self.agent_mod.BotRunner)
        a.name = "Scout"
        a.profile = {}
        a._script_tick = None
        a._script_loaded = True
        a._script_hold = None
        a._script_hold_seq = 0
        a._script_say_guard = self.agent_mod.ScriptSayGuard()
        a._result_slot = self.agent_mod.ResultSlot()
        a._lock = threading.Lock()
        a._l3_orchestrator_dispatch = mock.Mock(return_value="COMPLETED")
        a._run_directive = mock.Mock(return_value={"success": True})
        a._active_goal_id = "goal-A"
        # Set because `_script_goal_pending` (agent.py:4278) reads
        # `self._plan_instruction` unguarded, while its two neighbours on the
        # same expression use getattr. Not fixed here: it is outside this row.
        a._plan_instruction = ""

        class Stub:
            last_state = "script"
            last_deliveries = []
            last_result = None
            last_logs = []
            _revision = "sha256:abc"

            def tick(_self):
                return (True, [], [], "ok")

        a._script_tick = Stub()
        return a

    def test_a_sent_tick_produces_a_report(self):
        a = self._runner()
        rec, clock = Recorder(), FakeClock()
        a.script_reporter = sr.ReportSender(rec, clock=clock)
        a._run_script_tick()
        self.assertEqual(len(rec.sent), 1, "a sent tick reported nothing")
        name, body = rec.sent[0]
        self.assertEqual(name, "Scout")
        self.assertEqual(body["script_state"], "script")
        self.assertIn("code_hours", body)

    def test_a_tick_that_never_reached_the_runner_skips_the_report(self):
        """F-3: `last_state` is None on the three early returns (no script, no
        runner, no token), and `report()` raises on a state outside the
        vocabulary. The seam's blanket `except` used to swallow that as though
        it were a transport failure -- losing the report without counting it in
        `dropped`. It must be a clean skip instead, and must not be a send."""
        a = self._runner()

        class NeverTicked:
            last_state = None
            last_deliveries = []
            last_result = None
            last_logs = []
            _revision = "sha256:abc"

            def tick(_self):
                return (False, [], [], "no script")

        a._script_tick = NeverTicked()
        rec = Recorder()
        sender = sr.ReportSender(rec, clock=FakeClock())
        a.script_reporter = sender
        # Spy on `report`: a clean skip never enters it, whereas the old
        # pass-through called it with `None`, raised, and had that swallowed by
        # the seam's blanket `except`. Asserting only `rec.sent == []` does NOT
        # distinguish the two -- both send nothing -- which is why this is a
        # call-count assertion.
        calls = []
        real_report = sender.report

        def spy(*args, **kw):
            calls.append(args)
            return real_report(*args, **kw)

        sender.report = spy
        a._run_script_tick()  # must not raise
        self.assertEqual(rec.sent, [], "a tick that never reached the runner reported")
        self.assertEqual(calls, [], "report() was called with no runner state; "
                                    "the skip must happen before it")
        self.assertEqual(sender.dropped, 0, "a skip was counted as a dropped report")

    def test_a_held_tick_reports_nothing(self):
        # A held script does not tick, so it must not report: reporting would
        # tell the mod the bot is running a script it is not running.
        a = self._runner()
        a._script_hold = {"goal_id": "g1"}
        rec = Recorder()
        a.script_reporter = sr.ReportSender(rec, clock=FakeClock())
        a._run_script_tick()
        self.assertEqual(rec.sent, [])

    def test_no_reporter_attached_is_a_noop(self):
        """Every existing caller has no reporter; the seam must not change.

        The stub proposes nothing, so the real body returns False for an idle
        tick (agent.py:3780-ish). Writing `assertTrue` here was my mistake: the
        property is that the return value is UNCHANGED by the reporting seam,
        not that it is True. Asserting True tested my stub, not the seam.
        """
        a = self._runner()
        self.assertFalse(a._run_script_tick(), "idle tick should return False")
        # The attribute not existing at all IS the no-op case, so read it with
        # a default rather than touching it directly.
        self.assertIsNone(getattr(getattr(a, "script_reporter", None), "sent", None))

    def test_a_broken_reporter_cannot_break_the_tick(self):
        a = self._runner()

        class Boom:
            def report(self, *a, **k):
                raise RuntimeError("reporter bug")

        a.script_reporter = Boom()
        # Same property: the tick's own outcome survives a reporter failure.
        # Run a no-reporter runner identically and require the same result.
        plain = self._runner()
        self.assertEqual(a._run_script_tick(), plain._run_script_tick(),
                         "a reporter failure changed the tick's result")

    def test_observed_at_is_the_documented_shape(self):
        stamp = self.agent_mod.BotRunner._report_observed_at()
        self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


if __name__ == "__main__":
    unittest.main()

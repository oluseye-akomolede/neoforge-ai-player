"""A stop or reset supersedes a re-plan already in flight.

Written against "A Stop Or Reset Cancels The Work That Would Outlive It".

Live 2026-11-22 07:01:40Z, bot Mystic, goal yielded and re-planning:

    [Mystic/cancel] aborting orchestrator (nav shortcut: stop)
    [Mystic/nav] Direct stop (shortcut)
    [Mystic/script] bound (planner, in memory) (0b62fe044f914f1b)   <-- after
    ... another re-plan ...
    [Mystic/script] bound (planner, in memory) (7df52ecc6ec16e7a)   <-- after
    [Mystic/script] no re-plan: re-plan bound reached (3)

`_cancel_orchestrator` signals only the run executing at that moment. The
re-plan is a NEW thread that starts after the stop and never observes an
event set before it began, so it planned and bound anyway and the yield loop
kept re-planning a goal the player had ended.

These tests drive the real `_resubmit_yielded_goal` and the real
`_bind_planner_script` rather than hand-setting a flag: the defect lived in
the ordering between two production methods, so a fixture that asserts the
flag in isolation would pass with both call sites removed.
"""

import unittest
from unittest import mock

# Reused, not copied: imports the stub modules agent.py needs at module scope.
import test_agent_script_branch  # noqa: F401

import inspect as _inspect
import agent as agent_mod


def _runner(**attrs):
    """A BotRunner without __init__, as the rest of this suite already builds one."""
    bot = agent_mod.BotRunner.__new__(agent_mod.BotRunner)
    bot.name = "Mystic"
    bot._lock = agent_mod.threading.RLock()
    bot._goal_generation = 0
    bot._replan_goal_id = ""
    bot._replan_attempts = 0
    bot._active_goal_id = ""
    bot._active_goal_text = ""
    bot._plan_instruction = ""
    bot._planner_script = None
    bot._script_tick = None
    bot._script_loaded = False
    for k, v in attrs.items():
        setattr(bot, k, v)
    return bot


class StopSupersedesInFlightWorkTest(unittest.TestCase):

    def test_stop_supersedes_the_generation(self):
        bot = _runner()
        with mock.patch.object(agent_mod, "print", create=True):
            bot._supersede_goal(reason="stop")
        self.assertEqual(bot._goal_generation, 1)
        self.assertTrue(bot._goal_generation_is_stale(0))
        self.assertFalse(bot._goal_generation_is_stale(1))

    def test_a_run_captured_before_a_stop_is_stale_after_it(self):
        bot = _runner()
        bot._active_goal_generation = bot._goal_generation  # run starts
        bot._supersede_goal(reason="stop")                  # player stops
        self.assertTrue(bot._goal_generation_is_stale(bot._active_goal_generation))

    def test_no_captured_generation_is_never_stale(self):
        # The pre-change path: a caller that captured nothing must keep working
        # exactly as before, or shipping this unbinds every live script.
        bot = _runner()
        bot._supersede_goal(reason="stop")
        self.assertFalse(bot._goal_generation_is_stale(None))


class ResubmitIsRefusedAfterAStopTest(unittest.TestCase):
    """The re-plan path itself, not a flag standing in for it."""

    def test_replan_does_not_start_after_a_stop(self):
        bot = _runner(_active_goal_generation=0)
        bot._supersede_goal(reason="stop")
        with mock.patch.object(agent_mod.threading, "Thread") as thread:
            started = bot._resubmit_yielded_goal("chat:p:mine ore#1", "mine ore")
        self.assertFalse(started, "a re-plan must not start for a stopped goal")
        thread.assert_not_called()

    def test_replan_starts_normally_without_a_stop(self):
        # The positive direction: without this the fix could refuse every
        # re-plan and the test above would still pass.
        bot = _runner(_active_goal_generation=0)
        with mock.patch.object(agent_mod.threading, "Thread") as thread:
            started = bot._resubmit_yielded_goal("chat:p:mine ore#1", "mine ore")
        self.assertTrue(started)
        thread.assert_called_once()


class BindIsRefusedAfterAStopTest(unittest.TestCase):
    """The last line of defence: a plan finishing after the stop binds nothing."""

    def test_bind_refused_when_the_generation_went_stale(self):
        bot = _runner(_active_goal_generation=0, _active_goal_id="chat:p:mine#1")
        bot._supersede_goal(reason="stop")
        with mock.patch.object(bot, "_dry_tick", return_value=True) as dry, \
                mock.patch.object(bot, "_bound_script_path", return_value=""):
            bound = bot._bind_planner_script("def on_tick(e):\n    return []\n")
        self.assertFalse(bound, "a stopped goal must not bind a script")
        self.assertIsNone(bot._planner_script)
        # The dry tick is a real cost and must not be paid for a bind that is
        # already known to be refused.
        dry.assert_not_called()

    def test_bind_succeeds_when_the_generation_is_current(self):
        bot = _runner(_active_goal_generation=0)
        with mock.patch.object(bot, "_dry_tick", return_value=True), \
                mock.patch.object(bot, "_bound_script_path", return_value=""), \
                mock.patch.object(agent_mod, "_script_digest", return_value="d"), \
                mock.patch.object(agent_mod, "_script_excerpt", return_value=""):
            bound = bot._bind_planner_script("def on_tick(e):\n    return []\n")
        self.assertTrue(bound)
        self.assertIsNotNone(bot._planner_script)


class ResetSupersedesInFlightWorkTest(unittest.TestCase):

    def test_reset_supersedes_and_a_new_goal_is_not_stale(self):
        bot = _runner()
        bot._active_goal_generation = bot._goal_generation
        bot._supersede_goal(reason="reset")
        self.assertTrue(bot._goal_generation_is_stale(bot._active_goal_generation))
        # A NEW run captures the current generation, so the next goal is
        # planned and can bind normally -- the spec's third scenario.
        fresh = bot._goal_generation
        self.assertFalse(bot._goal_generation_is_stale(fresh))



class StopClassificationTest(unittest.TestCase):
    """"Is this a stop?", and does a stop actually advance the generation?

    Without the second half the three guards in `_resubmit_yielded_goal`,
    `_bind_planner_script` and `_supersede_goal` are each tested by calling
    them directly, so a stop path that never advances the generation passes
    every test. Verified the hard way: removing the advance from the
    nav-shortcut branch left this file fully green, twice, until
    `_note_stop_supersedes` existed and was driven from here.
    """

    def test_a_bare_stop_is_a_stop(self):
        self.assertTrue(agent_mod.is_stop_instruction("stop"))
        self.assertTrue(agent_mod.is_stop_instruction("  Stop  "))

    def test_stop_phrases_are_stops(self):
        for text in ("stop following", "go idle", "halt", "stand still",
                     "stay here", "stay put", "wait here", "stop what you are doing"):
            self.assertTrue(agent_mod.is_stop_instruction(text), text)

    def test_goto_and_follow_are_not_stops(self):
        # These share the same branch and must NOT supersede the generation.
        for text in ("come here", "follow me", "come to me", "get over here",
                     "walk to me", "form up"):
            self.assertFalse(agent_mod.is_stop_instruction(text), text)

    def test_the_stop_path_advances_the_generation(self):
        # THE point of this class. Drives production's own method, so removing
        # the advance from it fails here rather than passing quietly.
        bot = _runner()
        before = bot._goal_generation
        with mock.patch.object(agent_mod, "print", create=True):
            bot._note_stop_supersedes("stop")
        self.assertEqual(bot._goal_generation, before + 1)
        self.assertTrue(bot._goal_generation_is_stale(before))

    def test_the_nav_branch_calls_the_stop_advance(self):
        # Pins the call site, which the method test above cannot see. The
        # mutation that survived removed exactly this line, not the method.
        src = _inspect.getsource(agent_mod.BotRunner._maybe_plan)
        self.assertIn("if is_stop:\n                    self._note_stop_supersedes(", src)
        self.assertIn("is_stop = is_stop_instruction(text_lower)", src)


if __name__ == "__main__":
    unittest.main()

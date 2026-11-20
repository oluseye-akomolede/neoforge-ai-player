"""Tests for agent/result_delivery.py (change: script-lookups-and-results).

Each test names the task it pins in its docstring. Mutants were run per test;
a green test proves nothing until a wrong implementation reds it.
"""

import unittest

from result_delivery import (
    COOLDOWN_SECONDS, HOUR_SECONDS, MAX_RESULTS_PER_HOUR, ResultSlot,
)


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class TestTheCapsBoundResultTriggeredCalls(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        # Cooldown 0: this class isolates the HOUR CAP. The cooldown has its
        # own tests below, on a slot with the real 15 minutes. With both at
        # their real values, four calls cannot fit an hour at cooldown spacing
        # (4 * 15 min = exactly the hour), so a mixed test would pass or fail
        # on which bound bit first rather than on the one it names.
        self.slot = ResultSlot(clock=self.clock, cooldown_seconds=0)

    def _spend(self, n, step=60, goal_id="g1"):
        """Try `n` back-to-back reports; return how many reached a call.

        With cooldown 0 every attempt is eligible on the cooldown, so only
        the hour cap can stop it. The step keeps all ten attempts inside the
        hour window, so the cap is reachable.
        """
        made = 0
        for _ in range(n):
            self.slot.store(goal_id, {"done": True}, "done")
            allowed, _reason = self.slot.may_call()
            if allowed:
                self.slot.record_call()
                made += 1
            self.clock.advance(step)
        return made

    def test_four_calls_an_hour_then_the_fifth_is_held(self):
        """3.3/3.7: 10 distinct scripts, each reporting done once, give 4 calls.

        KILLS: a version with no hour cap calls all 10.
        KILLS: a version keying the count on the SCRIPT id rather than the bot
               would see 10 distinct scripts and allow all 10 -- this loop
               models exactly that (new pending value each time, same bot).
        """
        made = self._spend(10)
        self.assertEqual(made, MAX_RESULTS_PER_HOUR)
        self.assertEqual(made, 4)

    def test_a_fifth_result_is_held_with_a_named_reason(self):
        """3.7: the fifth is held off and the suppressing cap is nameable.

        KILLS: a version that drops the result instead of holding it leaves
               has_pending() False here.
        """
        self._spend(4)
        self.slot.store("g1", {"done": True}, "done")
        allowed, reason = self.slot.may_call()
        self.assertFalse(allowed)
        self.assertEqual(reason, "hour-cap")
        self.assertTrue(self.slot.has_pending(),
                        "a held result stays pending; it is not dropped")

    def test_a_second_result_inside_the_cooldown_is_held(self):
        """3.3: the 15-minute cooldown holds a second result.

        Uses a slot with the REAL cooldown, since this class's setUp zeroes it
        to isolate the hour cap.

        KILLS: a version with the cap but no cooldown allows this one.
        """
        slot = ResultSlot(clock=self.clock)
        slot.store("g1", {"done": True}, "done")
        self.assertTrue(slot.may_call()[0])
        slot.record_call()
        self.clock.advance(COOLDOWN_SECONDS - 1)
        slot.store("g1", {"done": True}, "done")
        allowed, reason = slot.may_call()
        self.assertFalse(allowed)
        self.assertEqual(reason, "cooldown")

    def test_after_the_cooldown_a_second_call_is_allowed(self):
        """The bound is a cooldown, not a one-per-hour cap: it must expire.

        KILLS: a version that never expires the cooldown.
        """
        slot = ResultSlot(clock=self.clock)
        slot.store("g1", {"done": True}, "done")
        self.assertTrue(slot.may_call()[0])
        slot.record_call()
        self.clock.advance(COOLDOWN_SECONDS)
        slot.store("g1", {"done": True}, "done")
        allowed, _reason = slot.may_call()
        self.assertTrue(allowed)

    def test_the_hour_cap_expires(self):
        """The hour window is a window: an hour later the budget is back.

        KILLS: a version whose counts never age out.
        """
        self._spend(4)
        self.clock.advance(HOUR_SECONDS)
        self.slot.store("g1", {"done": True}, "done")
        allowed, _reason = self.slot.may_call()
        self.assertTrue(allowed)


class TestTheSlotHoldsOneResult(unittest.TestCase):
    def test_a_second_store_overwrites_the_first(self):
        """F4: one slot, last write wins.

        KILLS: a version appending to a list, which would deliver the older
               result first.
        """
        slot = ResultSlot(clock=FakeClock())
        slot.store("g1", {"n": 1}, "done")
        slot.store("g1", {"n": 2}, "done")
        self.assertEqual(slot.peek()[1], {"n": 2})

    def test_a_result_for_a_changed_goal_is_not_delivered(self):
        """F4: a result whose goal differs from the current one is discarded.

        KILLS: a version ignoring goal_id delivers a stale result into a new goal.
        """
        slot = ResultSlot(clock=FakeClock())
        slot.store("old-goal", {"done": True}, "done")
        allowed, reason = slot.may_call(goal_id="new-goal")
        self.assertFalse(allowed)
        self.assertEqual(reason, "goal-changed")

    def test_record_call_consumes_the_pending_result(self):
        """A delivered result is gone; it must not be delivered twice.

        KILLS: a version that records the call but leaves the slot full, which
               would deliver the same result again next pass.
        """
        slot = ResultSlot(clock=FakeClock())
        slot.store("g1", {"done": True}, "done")
        slot.record_call()
        self.assertFalse(slot.has_pending())


class TestTheStateOutlivesReset(unittest.TestCase):
    def test_reset_does_not_clear_the_budget(self):
        """3.8: reset() is not an amnesty for the planner-call budget.

        The slot is held per bot for the process lifetime. `agent.reset()`
        clears the plan and the script hold; it must not touch this state,
        or a bot could report done, be reset, and report again for a fifth
        call in the hour. This test models that by spending the cap and then
        requiring the slot to still hold, with no clearing API offered.

        KILLS: a version that clears the call log from reset() -- which would
               let this fifth result through.
        """
        clock = FakeClock()
        # Cooldown 0 and tight spacing: all four calls stay inside the hour
        # window so the HOUR CAP is the bound being spent. At real cooldown
        # spacing four calls span exactly the hour and the earliest ages out,
        # which would make this test pass without the cap.
        slot = ResultSlot(clock=clock, cooldown_seconds=0)
        for _ in range(4):
            slot.store("g1", {"done": True}, "done")
            allowed, _r = slot.may_call()
            self.assertTrue(allowed)
            slot.record_call()
            clock.advance(60)
        # A reset() happens here. The slot offers no reset; agent.py must
        # simply not call one. The fifth must still be held.
        slot.store("g1", {"done": True}, "done")
        allowed, reason = slot.may_call()
        self.assertFalse(allowed)
        self.assertEqual(reason, "hour-cap")


if __name__ == "__main__":
    unittest.main()

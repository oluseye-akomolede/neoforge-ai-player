"""Tests for agent/result_delivery.py (change: script-lookups-and-results).

Each test names the task it pins in its docstring. Mutants were run per test;
a green test proves nothing until a wrong implementation reds it.

Owner A2 (2026-11-25 00:59Z) removed the per-bot 4/hour cap and the 15-minute
cooldown. The tests that pinned them (the hour-cap and cooldown classes) and the
`reset()`-amnesty test that spent the cap are gone with the behaviour, not
skipped: they asserted a bound the product no longer has. What remains here is
the slot's own contract -- one pending result, keyed on its goal.
"""

import unittest

from result_delivery import ResultSlot


class TestTheSlotHoldsOneResult(unittest.TestCase):
    def test_a_second_store_overwrites_the_first(self):
        """F4: one slot, last write wins.

        KILLS: a version appending to a list, which would deliver the older
               result first.
        """
        slot = ResultSlot()
        slot.store("g1", {"n": 1}, "done")
        slot.store("g1", {"n": 2}, "done")
        self.assertEqual(slot.peek()[1], {"n": 2})

    def test_a_result_for_a_changed_goal_is_not_delivered(self):
        """F4: a result whose goal differs from the current one is discarded.

        KILLS: a version ignoring goal_id delivers a stale result into a new goal.
        """
        slot = ResultSlot()
        slot.store("old-goal", {"done": True}, "done")
        allowed, reason = slot.may_call(goal_id="new-goal")
        self.assertFalse(allowed)
        self.assertEqual(reason, "goal-changed")

    def test_record_call_consumes_the_pending_result(self):
        """A delivered result is gone; it must not be delivered twice.

        KILLS: a version that records the call but leaves the slot full, which
               would deliver the same result again next pass.
        """
        slot = ResultSlot()
        slot.store("g1", {"done": True}, "done")
        slot.record_call()
        self.assertFalse(slot.has_pending())


class TestNoRateCapRemains(unittest.TestCase):
    def test_pending_result_is_allowed_no_matter_how_many_were_delivered(self):
        """3.12 / A2: no hourly cap and no cooldown on result-triggered calls.

        Delivers many results back to back. A version that kept the 4/hour cap
        or the 15-minute cooldown would refuse one of these.

        KILLS: any re-introduced rate cap or cooldown inside may_call.
        """
        slot = ResultSlot()
        for i in range(10):
            slot.store("g1", {"n": i}, "done")
            allowed, reason = slot.may_call(goal_id="g1")
            self.assertTrue(allowed, f"call {i} refused: {reason}")
            slot.record_call()

    def test_the_only_refusals_left_are_identity(self):
        """A2: refusal reasons describe which result this is, not how often.

        KILLS: a version returning "hour-cap" or "cooldown", which cannot arise
               from a slot that no longer tracks call times.
        """
        slot = ResultSlot()
        self.assertEqual(slot.may_call(), (False, "no-result"))
        slot.store("g1", 1, "done")
        self.assertEqual(slot.may_call(goal_id="g2"), (False, "goal-changed"))


if __name__ == "__main__":
    unittest.main()

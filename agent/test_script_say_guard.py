"""Tests for ScriptSayGuard (change: script-say-dedupe, task 1.2).

The guard alone, with an injected clock: no bot, no agent, no runner. Each
test here has a mutant that reds it (task 4.3): the window comparison changed
from `<` to `<=`, the key dropping `to`, the key dropping `text`, and the
first-suppression flag never clearing.
"""

import unittest

from script_say_guard import ScriptSayGuard


class _Clock:
    """A monotonic clock the test drives by hand."""

    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class ScriptSayGuardTest(unittest.TestCase):

    def setUp(self):
        self.clock = _Clock()
        self.guard = ScriptSayGuard(clock=self.clock)

    def _deliver(self, call, text, to=None):
        """Deliver through the guard, asserting it allowed the delivery."""
        should, first = self.guard.check(call, text, to)
        self.assertTrue(should, "guard refused a delivery it should allow")
        self.assertFalse(first, "a delivery must never report a suppression")
        self.guard.deliver(call, text, to)

    def test_same_key_inside_the_window_is_suppressed(self):
        self._deliver("say", "all clear")
        self.clock.advance(10)
        should, first = self.guard.check("say", "all clear")
        self.assertFalse(should)
        self.assertTrue(first, "the first suppression of a window is logged")

    def test_window_boundary_is_exclusive_at_exactly_sixty(self):
        self._deliver("say", "all clear")

        self.clock.advance(59.999)
        should, _ = self.guard.check("say", "all clear")
        self.assertFalse(should, "59.999 s is inside the 60 s window")

        # 59.999 + 0.001 == 60.0 exactly from the delivery time.
        self.clock.advance(0.001)
        should, first = self.guard.check("say", "all clear")
        self.assertTrue(should, "at exactly 60.0 s the comparison is < 60.0, false")
        self.assertFalse(first)

    def test_different_text_is_delivered(self):
        self._deliver("say", "watching for diamond ore")
        should, _ = self.guard.check("say", "found diamond ore at -42, 12, 87")
        self.assertTrue(should, "a different line is never suppressed")

    def test_send_is_keyed_per_recipient(self):
        self._deliver("send", "on my way", "Scout")
        should, _ = self.guard.check("send", "on my way", "Builder")
        self.assertTrue(should, "the same text to a second bot is delivered")
        should, _ = self.guard.check("send", "on my way", "Scout")
        self.assertFalse(should, "the same text to the same bot is suppressed")

    def test_say_and_send_are_separate_streams(self):
        self._deliver("send", "go", "Scout")
        should, _ = self.guard.check("say", "go")
        self.assertTrue(should, "send('Scout', 'go') must not suppress say('go')")

    def test_alternating_keys_are_each_suppressed(self):
        self._deliver("say", "A")
        self._deliver("say", "B")
        self.clock.advance(10)
        self.assertFalse(self.guard.check("say", "A")[0])
        self.assertFalse(self.guard.check("say", "B")[0],
                         "alternating must not defeat the rule")

    def test_first_suppression_flag_is_true_once_then_false(self):
        self._deliver("say", "all clear")
        self.clock.advance(1)
        first_seen = []
        for _ in range(5):
            first_seen.append(self.guard.check("say", "all clear")[1])
            self.clock.advance(1)
        self.assertEqual(first_seen, [True, False, False, False, False],
                         "one log line per key per window, not one per tick")

    def test_a_new_window_logs_again(self):
        self._deliver("say", "all clear")
        self.clock.advance(1)
        self.assertTrue(self.guard.check("say", "all clear")[1])
        self.clock.advance(60)
        self._deliver("say", "all clear")
        self.clock.advance(1)
        self.assertTrue(self.guard.check("say", "all clear")[1],
                        "the flag resets when a delivery opens a new window")


if __name__ == "__main__":
    unittest.main()

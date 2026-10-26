"""The agent's readiness gate on GET /health.

Stdlib only: `python3 agent/tests/test_health_readiness.py` from the repo root.

The mod now answers three bodies, and only one of them means ready:
  200 {"status": "ok", ...}        ready
  200 {"status": "starting", ...}  API up, no tick yet        -> not ready
  503 {"status": "stalled", ...}   server thread stalled      -> not ready
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import api  # noqa: E402  (needs the path above)


class HealthIsReadyTest(unittest.TestCase):

    def test_ok_is_ready(self):
        self.assertTrue(api.health_is_ready(
            {"status": "ok", "mod": "aiplayermod", "bots": 0, "tick_age_seconds": 3}))

    def test_starting_is_not_ready_even_though_it_is_a_200(self):
        self.assertFalse(api.health_is_ready(
            {"status": "starting", "mod": "aiplayermod", "bots": 0, "tick_age_seconds": None}))

    def test_stalled_is_not_ready(self):
        self.assertFalse(api.health_is_ready(
            {"status": "stalled", "mod": "aiplayermod", "bots": 0,
             "tick_age_seconds": 300, "reason": "tick age 300 s exceeds threshold 120 s"}))

    def test_never_ticked_is_not_ready(self):
        self.assertFalse(api.health_is_ready(
            {"status": "stalled", "mod": "aiplayermod", "bots": 0,
             "tick_age_seconds": None, "reason": "never ticked"}))

    def test_unexpected_shapes_are_not_ready(self):
        for body in (None, [], "ok", {}, {"error": "boom"}, {"status": "OK"}):
            self.assertFalse(api.health_is_ready(body), repr(body))


if __name__ == "__main__":
    unittest.main()

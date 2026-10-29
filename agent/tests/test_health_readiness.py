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

    def test_a_404_body_is_not_ready_even_with_the_ok_shape_gone(self):
        # What the wrong port actually returns: {"error": "not found"} at 404.
        # The readiness gate must not read this as ready.
        self.assertFalse(api.health_is_ready({"error": "not found"}))


class HealthUrlTest(unittest.TestCase):
    """The health URL must follow the mod's dedicated probe port, not the API base."""

    def test_health_url_uses_the_probe_port_not_the_api_port(self):
        api_url, health_url = _fresh_config({})
        self.assertEqual("http://localhost:3101", health_url)
        self.assertEqual("http://localhost:3100", api_url)

    def test_health_url_follows_the_shared_probe_port_variable(self):
        api_url, health_url = _fresh_config({"AIPLAYER_HEALTH_PROBE_PORT": "3201"})
        self.assertEqual("http://localhost:3201", health_url)
        # The API base does not move with it.
        self.assertEqual("http://localhost:3100", api_url)

    def test_health_url_swaps_the_port_on_any_host(self):
        _, health_url = _fresh_config({"MOD_API_URL": "http://10.0.0.7:3100"})
        self.assertEqual("http://10.0.0.7:3101", health_url)

    def test_health_url_handles_a_base_with_no_port(self):
        # split(":") on this yields ["http", "//10.0.0.7"], so a naive swap builds
        # a wrong URL; the probe port must still land on the host.
        _, health_url = _fresh_config({"MOD_API_URL": "http://10.0.0.7"})
        self.assertEqual("http://10.0.0.7:3101", health_url)

    def test_health_url_handles_a_trailing_colon(self):
        # A base ending in ":" has an empty port, not a missing one.
        _, health_url = _fresh_config({"MOD_API_URL": "http://10.0.0.7:"})
        self.assertEqual("http://10.0.0.7:3101", health_url)

    def test_health_url_keeps_an_explicit_override(self):
        _, health_url = _fresh_config({"MOD_HEALTH_URL": "http://203.0.113.9:9999"})
        self.assertEqual("http://203.0.113.9:9999", health_url)


def _fresh_config(env):
    """config.py reads os.environ at import time, so evaluate it under a patched env.

    The values are captured BEFORE the environment is restored: importlib.reload
    mutates the module object in place, so returning the reloaded module from
    inside the try would hand back the object as it looks after the restore in
    the finally, and every assertion would silently read the default.
    """
    import importlib
    saved = dict(os.environ)
    try:
        os.environ.pop("MOD_API_URL", None)
        os.environ.pop("AIPLAYER_HEALTH_PROBE_PORT", None)
        os.environ.pop("MOD_HEALTH_URL", None)
        os.environ.update(env)
        module = importlib.reload(sys.modules["config"])
        # Capture into locals INSIDE the try. Returning the attributes directly
        # also works (the tuple is built before the finally runs), but it is one
        # edit away from the bug below the docstring warns about, and nothing in
        # the test would catch that regression. Locals make the capture explicit.
        api_url, health_url = module.MOD_API_URL, module.MOD_HEALTH_URL
        return api_url, health_url
    finally:
        os.environ.clear()
        os.environ.update(saved)
        importlib.reload(sys.modules["config"])


if __name__ == "__main__":
    unittest.main()

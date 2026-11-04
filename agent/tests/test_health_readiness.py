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


class HealthRequestHeaderTest(unittest.TestCase):
    """The probe port authenticates nothing, so /health must not carry the key.

    The receiving listener has no apiKey/auth reference at all, so the header is
    never checked. Sending it is harmless on one host today, but it is a live
    credential one listener change or forwarded port away from being exposed.
    """

    def test_health_request_carries_the_beacon_and_not_the_api_key(self):
        sent = _capture_health_request(env={"MOD_API_KEY": "live-secret-value"})
        self.assertNotIn("X-Api-Key", sent["headers"],
                         "the probe port ignores credentials; sending one is exposure with no benefit")
        self.assertEqual("aibot-agent", sent["headers"].get("X-Agent-Id"),
                         "dropping the beacon would make a healthy agent show as agent down")

    def test_health_request_has_no_api_key_even_when_the_key_is_empty(self):
        sent = _capture_health_request(env={"MOD_API_KEY": ""})
        self.assertNotIn("X-Api-Key", sent["headers"])
        self.assertEqual("aibot-agent", sent["headers"].get("X-Agent-Id"))

    def test_bot_calls_still_authenticate(self):
        # The fix must not leak into the API-port calls, which DO enforce auth.
        sent = _capture_api_request(env={"MOD_API_KEY": "live-secret-value"})
        self.assertEqual("live-secret-value", sent["headers"].get("X-Api-Key"))


class HealthTimeoutSettingTest(unittest.TestCase):
    """The startup gate's per-attempt timeout is a named setting, default 10 s."""

    def test_default_is_ten_seconds(self):
        sent = _capture_health_request(env={})
        self.assertEqual(10, sent["timeout"])

    def test_setting_is_honoured(self):
        # A defined-but-unread constant cannot satisfy this.
        sent = _capture_health_request(env={"AIPLAYER_HEALTH_TIMEOUT": "20"})
        self.assertEqual(20, sent["timeout"])

    def test_the_comment_names_the_setting_the_code_reads(self):
        # Read the file as text rather than importing it: agent.py pulls in
        # psycopg2 via semantic_memory, which this VM does not have, and the
        # comment is what is under test, not the module's import graph.
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "..", "agent.py"), encoding="utf-8") as f:
            src = f.read()
        # The retry comment used to name HEALTH_TIMEOUT with no definition
        # anywhere, so a reader who added one got a silent no-op.
        self.assertNotIn("HEALTH_TIMEOUT (10 s)", src)
        self.assertIn("config.HEALTH_TIMEOUT", src)


def _capture_health_request(env):
    """Call api.health() against a stubbed transport and return what was sent."""
    import importlib
    saved = dict(os.environ)
    try:
        for k in ("MOD_API_KEY", "AIPLAYER_HEALTH_TIMEOUT", "MOD_HEALTH_URL"):
            os.environ.pop(k, None)
        os.environ.update(env)
        importlib.reload(sys.modules["config"])
        api_mod = importlib.reload(sys.modules["api"])
        cap = {}

        class _Resp:
            @staticmethod
            def json():
                return {"status": "ok"}

        def _fake_get(url, headers=None, timeout=None, **kw):
            cap.update(url=url, headers=dict(headers or {}), timeout=timeout)
            return _Resp()

        real = api_mod.requests.get
        api_mod.requests.get = _fake_get
        try:
            api_mod.health()
        finally:
            api_mod.requests.get = real
        return cap
    finally:
        os.environ.clear()
        os.environ.update(saved)
        importlib.reload(sys.modules["config"])
        importlib.reload(sys.modules["api"])


def _capture_api_request(env):
    """Same, for an API-port call, to prove the key is still sent there."""
    import importlib
    saved = dict(os.environ)
    try:
        os.environ.pop("MOD_API_KEY", None)
        os.environ.update(env)
        importlib.reload(sys.modules["config"])
        api_mod = importlib.reload(sys.modules["api"])
        cap = {}

        class _Resp:
            @staticmethod
            def json():
                return {}

        def _fake_get(url, headers=None, timeout=None, **kw):
            cap.update(url=url, headers=dict(headers or {}), timeout=timeout)
            return _Resp()

        real = api_mod.requests.get
        api_mod.requests.get = _fake_get
        try:
            api_mod._get("/bots")
        finally:
            api_mod.requests.get = real
        return cap
    finally:
        os.environ.clear()
        os.environ.update(saved)
        importlib.reload(sys.modules["config"])
        importlib.reload(sys.modules["api"])


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


class HealthTimeoutSettingTest(unittest.TestCase):
    """A numeric setting must not be able to kill the process that reads it.

    config.py is imported before the startup health gate runs, so an
    unparseable AIPLAYER_HEALTH_TIMEOUT used to raise ValueError at import and
    take the agent down before the gate it configures could report anything.
    """

    def _timeout_under(self, env):
        """Import config with the given env and return HEALTH_TIMEOUT."""
        import contextlib
        import importlib
        import io
        saved = dict(os.environ)
        try:
            os.environ.pop("AIPLAYER_HEALTH_TIMEOUT", None)
            os.environ.update(env)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                module = importlib.reload(sys.modules["config"])
            return module.HEALTH_TIMEOUT, stderr.getvalue()
        finally:
            os.environ.clear()
            os.environ.update(saved)
            importlib.reload(sys.modules["config"])

    def test_defaults_to_ten_when_unset(self):
        self.assertEqual(self._timeout_under({})[0], 10.0)

    def test_reads_a_valid_value(self):
        self.assertEqual(self._timeout_under({"AIPLAYER_HEALTH_TIMEOUT": "25"})[0], 25.0)

    def test_bad_value_falls_back_and_warns_instead_of_crashing(self):
        value, err = self._timeout_under({"AIPLAYER_HEALTH_TIMEOUT": "abc"})
        self.assertEqual(value, 10.0)
        self.assertIn("AIPLAYER_HEALTH_TIMEOUT", err)
        self.assertIn("not a number", err)

    def test_empty_value_falls_back_to_default(self):
        self.assertEqual(self._timeout_under({"AIPLAYER_HEALTH_TIMEOUT": ""})[0], 10.0)


if __name__ == "__main__":
    unittest.main()

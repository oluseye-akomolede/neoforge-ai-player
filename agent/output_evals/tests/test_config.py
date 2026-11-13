"""Tests for the run config and the endpoint readiness probe."""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
for p in (REPO, os.path.join(REPO, "agent")):
    if p not in sys.path:
        sys.path.insert(0, p)

from output_evals import evalconfig  # noqa: E402


def write(text):
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    f.write(text)
    f.close()
    return f.name


class LoadTests(unittest.TestCase):
    def tearDown(self):
        for p in getattr(self, "_paths", []):
            os.unlink(p)

    def p(self, text):
        self._paths = getattr(self, "_paths", []) + [write(text)]
        return self._paths[-1]

    def test_minimal_config_gets_defaults(self):
        cfg = evalconfig.load_config(self.p("model: qwen3-coder:30b\n"))
        self.assertEqual(cfg.endpoint, "http://localhost:11434")
        self.assertEqual(cfg.timeout, 120)
        self.assertEqual(cfg.concurrency, 1)

    def test_model_and_endpoint_are_required_strings(self):
        with self.assertRaises(evalconfig.ConfigError):
            evalconfig.load_config(self.p("model: ''\n"))
        with self.assertRaises(evalconfig.ConfigError):
            evalconfig.load_config(self.p("endpoint: []\n"))

    def test_concurrency_above_one_refused(self):
        with self.assertRaises(evalconfig.ConfigError) as e:
            evalconfig.load_config(self.p("concurrency: 4\n"))
        self.assertIn("shared local model", str(e.exception))

    def test_missing_file_is_config_error_not_traceback(self):
        with self.assertRaises(evalconfig.ConfigError):
            evalconfig.load_config("/nonexistent/config.yaml")

    def test_describe_cites_the_path_read(self):
        path = self.p("model: qwen3-coder:30b\nendpoint: http://x:1/\n")
        cfg = evalconfig.load_config(path)
        self.assertIn(path, cfg.describe())
        self.assertIn("qwen3-coder:30b", cfg.describe())
        self.assertEqual(cfg.endpoint, "http://x:1")   # trailing slash trimmed


class EndpointTests(unittest.TestCase):
    def _cfg(self, endpoint):
        return evalconfig.Config(endpoint, "qwen3-coder:30b", 5, 1, "<test>", {})

    def test_dead_endpoint_fails(self):
        ok, why = evalconfig.check_endpoint(self._cfg("http://127.0.0.1:9"))
        self.assertFalse(ok)
        self.assertIn("did not answer", why)

    def test_tag_drift_is_distinguished_from_dead(self):
        # A server that answers with a different tag of the same family must
        # not be reported as unreachable: the remedy is a model pull, not a
        # network check.
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class H(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                body = b'{"models":[{"name":"qwen3-coder:7b"}]}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            ok, why = evalconfig.check_endpoint(
                self._cfg(f"http://127.0.0.1:{srv.server_port}"))
            self.assertFalse(ok)
            self.assertIn("tag drift", why)
        finally:
            srv.shutdown()


class CredentialNameTests(unittest.TestCase):
    def test_only_names_never_values(self):
        os.environ["EVAL_FAKE_TOKEN"] = "sk-should-never-appear"
        try:
            names = evalconfig.env_credential_names()
            self.assertIn("EVAL_FAKE_TOKEN", names)
            self.assertNotIn("sk-should-never-appear", names)
        finally:
            del os.environ["EVAL_FAKE_TOKEN"]


if __name__ == "__main__":
    unittest.main()

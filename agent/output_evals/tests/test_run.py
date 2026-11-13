"""End-to-end tests for the runner's refusals and its dry run.

Every test here asserts a way the runner must NOT behave: writing a report from
a dead endpoint, scoring zero cases, calling a model on a dry run.
"""
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
for p in (REPO, os.path.join(REPO, "agent")):
    if p not in sys.path:
        sys.path.insert(0, p)

from output_evals import run  # noqa: E402

CURRENT = "qwen3-coder:30b"


def _record_call(cid, phase, ref="p1"):
    return {"type": "call", "call_id": cid, "ts": "2026-11-13T10:00:00",
            "phase": phase, "bot": "scout", "model": CURRENT, "plan_ref": ref,
            "prompt_system": "s", "prompt_user": "u", "response_raw": "{}",
            "world_state_summary": "w"}


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self.tmp.name, "traj")
        os.makedirs(self.dir)
        self.cfg = os.path.join(self.tmp.name, "config.yaml")
        with open(self.cfg, "w") as f:
            f.write("model: %s\nendpoint: http://127.0.0.1:9\n" % CURRENT)
        self.out = os.path.join(self.tmp.name, "report.json")
        self.calls = 0

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, records):
        with open(os.path.join(self.dir, "trajectory-2026-11-13.jsonl"), "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

    def test_dead_endpoint_refuses_and_writes_no_report(self):
        self._write([_record_call("c1", "exec"),
                     {"type": "outcome", "call_id": "c1", "satisfied": True}])
        rc = run.main(["--config", self.cfg, "--trajectory-dir", self.dir,
                       "--out", self.out])
        self.assertEqual(rc, 2)
        self.assertFalse(os.path.exists(self.out),
                         "a report from a dead endpoint is the defect")

    def test_dry_run_makes_no_model_calls(self):
        self._write([_record_call("c1", "exec"),
                     {"type": "outcome", "call_id": "c1", "satisfied": True}])
        rc = run.main(["--config", self.cfg, "--trajectory-dir", self.dir,
                       "--out", self.out, "--dry-run"])
        self.assertEqual(rc, 0)
        with open(self.out) as f:
            rep = json.load(f)
        self.assertTrue(rep.get("dry_run"))
        self.assertEqual(rep["results"], {})
        self.assertEqual(rep["cases_per_kind"]["exec"], 1)

    def test_no_labelled_cases_exits_3(self):
        self._write([_record_call("c1", "exec")])   # no outcome
        rc = run.main(["--config", self.cfg, "--trajectory-dir", self.dir,
                       "--out", self.out, "--dry-run"])
        self.assertEqual(rc, 3)
        self.assertFalse(os.path.exists(self.out))

    def test_bad_config_exits_2(self):
        with open(self.cfg, "w") as f:
            f.write("model: ''\n")
        rc = run.main(["--config", self.cfg, "--trajectory-dir", self.dir,
                       "--out", self.out])
        self.assertEqual(rc, 2)

    def test_end_to_end_with_a_stub_model(self):
        """A real HTTP round trip: the reply is scored, the report is written."""
        reply = {"directives": [{"kind": "MINE", "count": 2}]}
        seen = []

        class H(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                body = json.dumps({"models": [{"name": CURRENT}]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):  # noqa: N802
                n = int(self.headers.get("Content-Length", 0))
                seen.append(json.loads(self.rfile.read(n)))
                body = json.dumps({"message": {"content": json.dumps(reply)}}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with open(self.cfg, "w") as f:
                f.write("model: %s\nendpoint: http://127.0.0.1:%d\n"
                        % (CURRENT, srv.server_port))
            recs = []
            for i in range(3):
                recs.append(_record_call(f"c{i}", "exec"))
                recs.append({"type": "outcome", "call_id": f"c{i}", "satisfied": True})
            self._write(recs)
            rc = run.main(["--config", self.cfg, "--trajectory-dir", self.dir,
                           "--out", self.out])
            self.assertEqual(rc, 0)
            with open(self.out) as f:
                rep = json.load(f)
            ex = rep["results"]["exec"]
            self.assertEqual(ex["n"], 3)
            self.assertEqual(ex["pass"], 3)
            self.assertTrue(ex["rate_withheld"], "a rate over 3 cases is withheld")
            self.assertEqual(len(seen), 3)
            self.assertEqual(seen[0]["model"], CURRENT)
        finally:
            srv.shutdown()

    def test_unscorable_reply_is_not_a_pass(self):
        class H(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                body = json.dumps({"models": [{"name": CURRENT}]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):  # noqa: N802
                n = int(self.headers.get("Content-Length", 0))
                self.rfile.read(n)
                body = json.dumps({"nope": 1}).encode()   # no message.content
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with open(self.cfg, "w") as f:
                f.write("model: %s\nendpoint: http://127.0.0.1:%d\n"
                        % (CURRENT, srv.server_port))
            self._write([_record_call("c0", "exec"),
                         {"type": "outcome", "call_id": "c0", "satisfied": True}])
            rc = run.main(["--config", self.cfg, "--trajectory-dir", self.dir,
                           "--out", self.out])
            self.assertEqual(rc, 0)
            with open(self.out) as f:
                rep = json.load(f)
            ex = rep["results"]["exec"]
            self.assertEqual(ex["unscorable"], 1)
            self.assertEqual(ex["pass"], 0)
        finally:
            srv.shutdown()


class DriftTests(unittest.TestCase):
    def row(self, n, rate):
        return {"n": n, "pass": int(n * rate), "rate": rate, "rate_withheld": n < 10}

    def test_gap_over_threshold_flags(self):
        res = run.flag_drift({"a": self.row(50, 0.50), "b": self.row(50, 0.80)})
        self.assertTrue(res["flagged"])
        self.assertEqual(res["gap_points"], 30.0)

    def test_small_gap_does_not_flag(self):
        self.assertFalse(run.flag_drift({"a": self.row(50, 0.50),
                                         "b": self.row(50, 0.60)})["flagged"])

    def test_small_n_withholds_the_flag(self):
        res = run.flag_drift({"a": self.row(9, 0.10), "b": self.row(50, 0.90)})
        self.assertFalse(res["flagged"])
        self.assertIn("fewer than two eras", res["reason"])


if __name__ == "__main__":
    unittest.main()

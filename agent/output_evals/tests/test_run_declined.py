"""A clarify/refuse answer is counted, not passed and not hidden.

The defect this pins: score_plan returned PASS for any clarify or refuse. With
the verdict passed through untouched, a model that answered every plan case with
"clarify" scored 25/25 -- the same as one that wrote 25 good plans. The report
could not tell them apart, and the number that reached the lead described a model
that never planned as perfect.
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

MODEL = "qwen3-coder:30b"


def _case(kind, cid):
    return {"kind": kind, "call_id": cid, "bot": "scout", "model": MODEL,
            "prompt_system": "s", "prompt_user": "u",
            "world_state_summary": "w", "recorded_output": "{}",
            "label": "", "label_source": ""}


class DeclinedReportingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self.tmp.name, "cases")
        os.makedirs(self.dir)
        self.cfg = os.path.join(self.tmp.name, "config.yaml")
        self.out = os.path.join(self.tmp.name, "report.json")

    def tearDown(self):
        self.tmp.cleanup()

    def _serve(self, reply_obj):
        payload = json.dumps({"message": {"content": json.dumps(reply_obj)}}).encode()

        class H(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                body = json.dumps({"models": [{"name": MODEL}]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):  # noqa: N802
                n = int(self.headers.get("Content-Length", 0))
                self.rfile.read(n)
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *a):
                pass

        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        return srv

    def test_clarify_plans_are_counted_and_not_passed(self):
        srv = self._serve({"kind": "clarify", "reason": "which chest?"})
        with open(self.cfg, "w") as f:
            f.write("model: %s\nendpoint: http://127.0.0.1:%d\n"
                    % (MODEL, srv.server_port))
        cases = [_case("plan", "p1"), _case("plan", "p2"), _case("plan", "p3")]
        with open(os.path.join(self.dir, "plan.jsonl"), "w") as f:
            for c in cases:
                f.write(json.dumps(c) + "\n")
        rc = run.main(["--config", self.cfg, "--cases-in", self.dir,
                       "--out", self.out])
        self.assertEqual(rc, 0)
        with open(self.out) as f:
            res = json.load(f)["results"]["plan"]

        # The count is the headline: every clarify is visible as a clarify.
        self.assertEqual(res["declined"], {"clarify": 3},
                         "the report must say how many answers were a clarify")
        # And they did not inflate the pass count.
        self.assertEqual(res["pass"], 0,
                         "a clarify must not be counted as a passing plan")
        self.assertEqual(res["fail"], 3)

    def test_refuse_is_counted_separately_from_fail_reason(self):
        srv = self._serve({"kind": "refuse", "reason": "cannot"})
        with open(self.cfg, "w") as f:
            f.write("model: %s\nendpoint: http://127.0.0.1:%d\n"
                    % (MODEL, srv.server_port))
        with open(os.path.join(self.dir, "plan.jsonl"), "w") as f:
            f.write(json.dumps(_case("plan", "p1")) + "\n")
        rc = run.main(["--config", self.cfg, "--cases-in", self.dir,
                       "--out", self.out])
        self.assertEqual(rc, 0)
        with open(self.out) as f:
            res = json.load(f)["results"]["plan"]
        self.assertEqual(res["declined"], {"refuse": 1})
        # A refusal is a different result from a malformed plan, so it is
        # counted in both places rather than being folded into one bucket.
        self.assertEqual(sum(res["fail_reasons"].values()), 1)

    def test_clean_plan_reports_an_empty_declined_map(self):
        """Absent and empty must be distinguishable.

        A report from older code has no `declined` key at all; a report from a
        run where nothing was declined has the key and it is empty. Conflating
        them lets a stale report read as a clean one.
        """
        srv = self._serve({"task": "t", "subtasks": [
            {"id": 1, "description": "d", "criteria": "c"}]})
        with open(self.cfg, "w") as f:
            f.write("model: %s\nendpoint: http://127.0.0.1:%d\n"
                    % (MODEL, srv.server_port))
        with open(os.path.join(self.dir, "plan.jsonl"), "w") as f:
            f.write(json.dumps(_case("plan", "p1")) + "\n")
        rc = run.main(["--config", self.cfg, "--cases-in", self.dir,
                       "--out", self.out])
        self.assertEqual(rc, 0)
        with open(self.out) as f:
            res = json.load(f)["results"]["plan"]
        self.assertIn("declined", res, "the key is present even when empty")
        self.assertEqual(res["declined"], {})
        self.assertEqual(res["pass"], 1)


if __name__ == "__main__":
    unittest.main()

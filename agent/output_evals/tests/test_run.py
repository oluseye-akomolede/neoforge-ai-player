"""End-to-end tests for the runner's refusals and its dry run.

Every test here asserts a way the runner must NOT behave: writing a report from
a dead endpoint, scoring zero cases, calling a model on a dry run.
"""
import contextlib
import io
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

    def test_cases_in_path_is_exercised_by_the_job_and_works(self):
        """--cases-in is how the Job actually runs; nothing else covers it.

        Every other test here goes through --trajectory-dir. The Job scores a
        pre-built ConfigMap set, and on that path per_kind is not sampled, so
        an unguarded reference to it crashed before any model was called.
        """
        cases = os.path.join(self.tmp.name, "cases")
        os.makedirs(cases)
        with open(os.path.join(cases, "exec.jsonl"), "w") as f:
            f.write(json.dumps({"kind": "exec", "call_id": "c1", "bot": "scout",
                                "model": CURRENT, "prompt_system": "s",
                                "prompt_user": "u", "world_state_summary": "w",
                                "recorded_output": "{}", "label": "",
                                "label_source": ""}) + "\n")
        rc = run.main(["--config", self.cfg, "--cases-in", cases,
                       "--out", self.out, "--dry-run"])
        self.assertEqual(rc, 0, "the --cases-in path must not crash")
        with open(self.out) as f:
            rp = json.load(f)["run_parameters"]
        self.assertIsNone(rp["per_kind"], "no sampling happened on this path")
        self.assertEqual(rp["per_kind_source"], "cases-in (set built by write_cases)")
        self.assertEqual(rp["cases_total"], 1)

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

    def test_dry_run_does_not_probe_the_endpoint(self):
        """A dry run reports the case set, so a dead endpoint must not gate it.

        It also must not PRINT a refusal it does not honour: an earlier version
        probed, printed REFUSED, and then exited 0 with a report. Both halves
        are asserted -- rc 0 with a report, and no REFUSED in the output.
        """
        self._write([_record_call("c1", "exec"),
                     {"type": "outcome", "call_id": "c1", "satisfied": True}])
        with open(self.cfg, "w") as f:
            # A port nothing listens on, so a probe would fail loudly if made.
            f.write("endpoint: http://127.0.0.1:9\nmodel: qwen3-coder:30b\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = run.main(["--config", self.cfg, "--trajectory-dir", self.dir,
                           "--out", self.out, "--dry-run"])
        self.assertEqual(rc, 0, "a dry run must not be gated on the endpoint")
        self.assertTrue(os.path.exists(self.out))
        self.assertNotIn("REFUSED", buf.getvalue(),
                         "printed a refusal the run did not honour")
        with open(self.out) as f:
            rep = json.load(f)
        self.assertFalse(rep.get("endpoint_probed"))

    def test_unlabelled_but_replayable_does_not_exit_3(self):
        """An unlabelled call is a usable REPLAY case; the run must proceed.

        Exit 3 is 'nothing to score', not 'nothing labelled'. Replay scores a
        fresh output, so a recorded outcome is not required.
        """
        self._write([_record_call("c1", "exec")])   # no outcome, but an input
        rc = run.main(["--config", self.cfg, "--trajectory-dir", self.dir,
                       "--out", self.out, "--dry-run"])
        self.assertEqual(rc, 0, "an unlabelled but replayable call is not empty")
        self.assertTrue(os.path.exists(self.out))

    def test_no_replayable_cases_exits_3(self):
        """A call with no usable input is not a case; an empty set is exit 3."""
        rec = _record_call("c1", "exec")
        rec["prompt_user"] = ""          # nothing to re-send: not replayable
        self._write([rec])
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
            # Every fail is counted by reason, so a reader can tell six shapes
            # of wrong from one repeated six times. Present and empty when
            # nothing failed -- an absent key would be indistinguishable from a
            # report written by older code.
            self.assertEqual(ex["fail_reasons"], {})
        finally:
            srv.shutdown()

    def test_unscorable_only_kind_reports_no_adherence_rate(self):
        """Nothing measured is None, not a rate that looks like a bad one.

        The reviewer's residual: pinning 0.0 proves a measured zero, but says
        nothing about the empty case, so an "unmeasured" sentinel such as -1.0
        would stay green. A kind whose only case was unscorable has no
        directives to count, and 0.0 there would read as total non-adherence.
        """

        class H(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                body = json.dumps({"models": [{"name": CURRENT}]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):  # noqa: N802
                self.send_response(500)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *a):
                pass

        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with open(self.cfg, "w") as f:
                f.write("model: %s\nendpoint: http://127.0.0.1:%d\n"
                        % (CURRENT, srv.server_port))
            d = os.path.join(self.tmp.name, "cases")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "exec.jsonl"), "w") as f:
                f.write(json.dumps({"kind": "exec", "call_id": "c1",
                                    "bot": "scout", "model": CURRENT,
                                    "prompt_system": "s", "prompt_user": "u",
                                    "world_state_summary": "w",
                                    "recorded_output": "{}", "label": "",
                                    "label_source": ""}) + "\n")
            rc = run.main(["--config", self.cfg, "--cases-in", d,
                           "--out", self.out])
            self.assertEqual(rc, 0)
            with open(self.out) as f:
                ex = json.load(f)["results"]["exec"]
            self.assertEqual(ex["unscorable"], 1, "the case must not score")
            self.assertIsNone(ex["single_directive_rate"],
                              "no directives were read, so there is no rate; "
                              "a number here is a claim nothing measured")
        finally:
            srv.shutdown()

    def test_single_directive_adherence_is_reported(self):
        """A SKILL-plus-noise answer must not look like a clean one.

        The prompt asks for exactly ONE directive. {"directives":[SKILL,
        GOTO...]} passes the scorer, and detail carries n=6 -- but nothing in
        the report read detail, so it scored identically to a clean answer and
        the baseline could not show how often the model disobeyed in count.
        """
        seen = []
        reply = {"directives": [
            {"kind": "SKILL", "target": "mine_and_smelt"},
            {"kind": "GOTO", "target": "chest"},
            {"kind": "GOTO", "target": "chest"},
        ]}

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
            import output_evals.extract as ex
            self._write([
                {"type": "call", "call_id": "k1", "phase": "exec", "bot": "scout",
                 "model": CURRENT, "prompt_system": "s", "prompt_user": "u",
                 "response_raw": json.dumps(reply),
                 "world_state_summary": "w"},
                {"type": "outcome", "call_id": "k1", "satisfied": True},
            ])
            d = os.path.join(self.dir, "cases")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "exec.jsonl"), "w") as f:
                f.write(json.dumps({"kind": "exec", "call_id": "k1", "bot": "scout",
                                    "model": CURRENT, "prompt_system": "s",
                                    "prompt_user": "u", "world_state_summary": "w",
                                    "recorded_output": json.dumps(reply),
                                    "label": "", "label_source": ""}) + "\n")
            rc = run.main(["--config", self.cfg, "--cases-in", d,
                           "--out", self.out])
            self.assertEqual(rc, 0)
            with open(self.out) as f:
                ex_res = json.load(f)["results"]["exec"]
            self.assertEqual(ex_res["n"], 1)
            self.assertEqual(ex_res["pass"], 1, "a noisy SKILL still passes")
            # The point: the report says the answer carried 3 directives and
            # that it was not a single-directive answer.
            self.assertEqual(ex_res["directives_per_answer"], {"3": 1},
                             "the report must record how many directives the "
                             "model actually emitted")
            self.assertEqual(ex_res["single_directive_rate"], 0.0,
                             "a 3-directive answer is not adherence to "
                             "'exactly ONE directive'")
            # 0.0 must be a MEASURED zero: a value arrived at by dividing, not
            # a "nothing measured" sentinel. An unmeasured branch returning
            # -1.0, or a string, would satisfy a truthiness check and no one
            # would notice. Pin the type, and pin the empty-case separately so
            # the two are distinguishable by assertion, not by consequence.
            self.assertIs(type(ex_res["single_directive_rate"]), float)
        finally:
            srv.shutdown()

    def test_think_reaches_the_request_and_both_report_paths(self):
        """think is sent on the wire and reported by a real run and a dry run.

        The reviewer's finding: build_report and the dry-run path each list
        config fields explicitly, so a field added to one and not the other
        reports nothing precisely on the dry run the lead uses to check a
        config before spending 75 cases.
        """
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
                body = json.dumps({"message": {"content": "{}"}}).encode()
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
                f.write("model: %s\nendpoint: http://127.0.0.1:%d\nthink: true\n"
                        % (CURRENT, srv.server_port))
            self._write([_record_call("c0", "exec"),
                         {"type": "outcome", "call_id": "c0", "satisfied": True}])
            rc = run.main(["--config", self.cfg, "--trajectory-dir", self.dir,
                           "--out", self.out])
            self.assertEqual(rc, 0)
            self.assertIs(seen[0].get("think"), True,
                          "think must be a real bool on the wire, not omitted")
            with open(self.out) as f:
                run_cfg = json.load(f)["config"]
            self.assertIs(run_cfg["think"], True)
            self.assertEqual(run_cfg["think_source"], "file")

            dry = os.path.join(self.tmp.name, "dry.json")
            rc = run.main(["--config", self.cfg, "--trajectory-dir", self.dir,
                           "--out", dry, "--dry-run"])
            self.assertEqual(rc, 0)
            with open(dry) as f:
                dry_cfg = json.load(f)["config"]
            self.assertIs(dry_cfg["think"], True, "a dry run must report think too")
            self.assertEqual(dry_cfg["think_source"], "file")
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

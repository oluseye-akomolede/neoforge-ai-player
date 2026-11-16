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
import unittest.mock
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

    def test_every_case_appears_in_the_report_not_just_five(self):
        """The 11-15 review was argued from 5 captured examples.

        Eight named cases changed verdict; only five were visible. The report
        must carry a row per case so the next before/after diff is mechanical.
        Uses a real (stubbed) model: --dry-run returns before run() and writes
        an empty results block, so it cannot exercise this at all.
        """
        reply = {"directives": [{"kind": "MINE", "count": 1}]}

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
                body = json.dumps(
                    {"message": {"content": json.dumps(reply)}}).encode()
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
            d = os.path.join(self.dir, "cases")
            os.makedirs(d, exist_ok=True)
            ids = [f"c{i}" for i in range(7)]
            with open(os.path.join(d, "exec.jsonl"), "w") as f:
                for cid in ids:
                    f.write(json.dumps({
                        "kind": "exec", "call_id": cid, "bot": "scout",
                        "model": CURRENT, "prompt_system": "s",
                        "prompt_user": "u", "world_state_summary": "w",
                        "recorded_output": json.dumps(reply),
                        "label": "", "label_source": ""}) + "\n")
            rc = run.main(["--config", self.cfg, "--cases-in", d,
                           "--out", self.out])
            self.assertEqual(rc, 0)
            with open(self.out) as f:
                rows = json.load(f)["results"]["exec"]["cases"]
            self.assertEqual(len(rows), 7,
                             "all 7 cases, not a 5-row sample")
            self.assertEqual([r["call_id"] for r in rows], sorted(ids),
                             "sorted by call_id so two reports diff cleanly")
            for r in rows:
                for key in ("call_id", "bot", "model", "verdict", "shape",
                            "reason"):
                    self.assertIn(key, r)
        finally:
            srv.shutdown()

    def test_diff_reports_names_who_moved(self):
        """The diff is the product: which cases changed, and how.

        A count-only comparison would have reported 'plan 15 -> 12' and left
        the cause to be guessed from five examples.
        """
        before = {"results": {"exec": {"cases": [
            {"call_id": "a", "verdict": "pass", "shape": None},
            {"call_id": "b", "verdict": "pass", "shape": None},
            {"call_id": "c", "verdict": "fail", "shape": "refuse"},
        ]}}}
        after = {"results": {"exec": {"cases": [
            {"call_id": "a", "verdict": "pass", "shape": None},
            {"call_id": "b", "verdict": "fail", "shape": "refuse"},
            {"call_id": "c", "verdict": "pass", "shape": None},
        ]}}}
        d = run.diff_reports(before, after)
        self.assertEqual(d["n_moved"], 2)
        moved = {m["call_id"]: m for m in d["moved"]}
        self.assertEqual(moved["b"]["before"], "pass")
        self.assertEqual(moved["b"]["after_shape"], "refuse",
                         "a pass turning into a refusal must name the shape")
        self.assertEqual(moved["c"]["before_shape"], "refuse")
        self.assertTrue(d["case_sets_identical"])
        self.assertNotIn("a", moved, "unchanged cases are not noise")

    def test_diff_reports_flags_a_shape_change_at_the_same_verdict(self):
        """pass->pass with a different shape is still a movement.

        The 11-15 regression was partly this: cases moved between clarify and
        refuse without either being a 'pass'. A verdict-only comparison calls
        them unchanged and hides the whole finding. Caught by mutation: a
        diff that compares only verdict left every other test green.
        """
        before = {"results": {"plan": {"cases": [
            {"call_id": "x", "verdict": "fail", "shape": "clarify"}]}}}
        after = {"results": {"plan": {"cases": [
            {"call_id": "x", "verdict": "fail", "shape": "refuse"}]}}}
        d = run.diff_reports(before, after)
        self.assertEqual(d["n_moved"], 1,
                         "clarify -> refuse is a change even though neither "
                         "verdict moved")
        self.assertEqual(d["moved"][0]["before_shape"], "clarify")
        self.assertEqual(d["moved"][0]["after_shape"], "refuse")

    def test_diff_reports_flags_a_changed_case_set(self):
        """Comparing different case sets must say so, not compare anyway."""
        before = {"results": {"exec": {"cases": [
            {"call_id": "a", "verdict": "pass", "shape": None}]}}}
        after = {"results": {"exec": {"cases": [
            {"call_id": "a", "verdict": "pass", "shape": None},
            {"call_id": "z", "verdict": "fail", "shape": "refuse"}]}}}
        d = run.diff_reports(before, after)
        self.assertFalse(d["case_sets_identical"])
        self.assertEqual(d["only_after"], ["z"])
        self.assertEqual(d["n_moved"], 0,
                         "a case present in one side is not a 'movement'")

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


class ScorerSurfaceTests(unittest.TestCase):
    """A surface that will not load must refuse, not report.

    The 18:38Z run: the Job packed output_evals standalone, the scorers could
    not import `action_binding` from the agent package, and every case came back
    unscorable -- while the run exited 0 and wrote a report. A reader cannot
    tell that from a model that genuinely answers nothing.
    """

    def test_the_real_surface_loads(self):
        ok, why = run.precheck_scorers()
        self.assertTrue(ok, why)

    def test_a_failed_import_is_refused_and_writes_no_report(self):
        """Exit 9, no report -- proven on main(), not on the helper alone."""
        tmp = tempfile.TemporaryDirectory()
        try:
            cfg = os.path.join(tmp.name, "config.yaml")
            with open(cfg, "w") as f:
                f.write("model: %s\nendpoint: http://127.0.0.1:9\n" % CURRENT)
            out = os.path.join(tmp.name, "report.json")
            boom = ImportError("No module named 'action_binding'")
            with unittest.mock.patch.object(run, "precheck_scorers",
                                            return_value=(False, str(boom))):
                rc = run.main(["--config", cfg, "--out", out])
            self.assertEqual(rc, 9, "a dead scorer surface is its own exit code")
            self.assertFalse(os.path.exists(out),
                             "a report from a surface that did not load is the "
                             "18:38Z defect")
        finally:
            tmp.cleanup()

    def test_an_unloadable_action_surface_is_refused(self):
        """The 18:38Z shape, reproduced for real rather than mocked.

        planner._load_surface() swallows the action_binding failure and caches
        it, so the MODULE imports cleanly and SCORERS stays populated: an
        import-only check returns True here and the run then scores every case
        unscorable. Only reading the surface's own error catches it. Both are
        asserted below -- the import still works, and the precheck still fails.
        """
        from output_evals.scorers import planner

        # Inject a planner whose surface reports the swallowed failure. The
        # test no longer touches sys.modules at all (reviewer T1, option b):
        # under `discover -t .` a real import could still succeed inside a
        # block that set the surface names to None, so blocking imports was
        # never the property under test -- the property is "precheck refuses
        # when the surface reports an error", and a stub states it directly.
        class _SwallowedFailure:
            SCORERS = dict(planner.SCORERS)   # populated: the whole trap

            @staticmethod
            def _load_surface():
                return None, "action_binding did not import"

        ok, why = run.precheck_scorers(planner_module=_SwallowedFailure)
        # The registry is populated and the module is importable, which is
        # exactly why an import-only precheck passed while the defect survived.
        self.assertTrue(_SwallowedFailure.SCORERS,
                        "SCORERS is populated regardless -- that is the trap")
        self.assertFalse(ok, "an unloadable surface must be refused")
        self.assertIn("surface", why)

    def test_a_registry_missing_a_kind_is_refused(self):
        """Importing is not enough: a registry that registers nothing measures
        nothing, and an import-only check would pass it."""
        with unittest.mock.patch.dict(run.planner.SCORERS, clear=True):
            ok, why = run.precheck_scorers()
        self.assertFalse(ok)
        self.assertIn("missing", why)


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


class DeclineLabelTests(unittest.TestCase):
    """The labels make a correct refusal visible. Untested until now.

    The counters were proven to move by hand, through a stub endpoint, but a
    mechanism only verified by hand is one refactor from silently reporting
    zero -- and a zero here reads as "no declines", which is the opposite of
    what a run full of refusals means.
    """

    def write(self, labels):
        fh = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"labels": labels}, fh)
        fh.close()
        self.addCleanup(os.unlink, fh.name)
        return fh.name

    def test_all_three_verdicts_are_accepted(self):
        """'plan' is the one that matters: it marks a decline as WRONG."""
        got = run.load_decline_labels(self.write([
            {"call_id": "a", "verdict": "refuse", "why": "impossible"},
            {"call_id": "b", "verdict": "clarify", "why": "vague"},
            {"call_id": "c", "verdict": "plan", "why": "achievable"},
        ]))
        self.assertEqual(got["a"]["wanted"], "refuse")
        self.assertEqual(got["c"]["wanted"], "plan")

    def test_absent_file_is_empty_not_an_error(self):
        """An unlabelled run must still run: it simply cannot judge declines."""
        self.assertEqual(run.load_decline_labels(None), {})
        self.assertEqual(run.load_decline_labels(""), {})

    def test_refuse_may_not_be_the_alternative(self):
        """Refusing an ask with a defensible non-refusal answer is the defect.

        Letting 'refuse' sit in alt_verdict would score exactly the behaviour
        this file exists to catch as correct.
        """
        with self.assertRaises(ValueError):
            run.load_decline_labels(self.write([
                {"call_id": "a", "verdict": "plan", "alt_verdict": "refuse"}]))

    def test_unknown_verdict_and_duplicates_are_refused(self):
        with self.assertRaises(ValueError):
            run.load_decline_labels(self.write([
                {"call_id": "a", "verdict": "shrug"}]))
        with self.assertRaises(ValueError):
            run.load_decline_labels(self.write([
                {"call_id": "a", "verdict": "refuse"},
                {"call_id": "a", "verdict": "plan"}]))

    def test_the_shipped_file_loads_and_keeps_its_alternative(self):
        """The real file, not a fixture: it must stay parseable in the bundle."""
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(here, "case_labels.json")
        got = run.load_decline_labels(path)
        self.assertTrue(got, "shipped case_labels.json loaded empty")
        for cid, label in got.items():
            self.assertIn(label["wanted"], ("plan", "refuse", "clarify"))
            self.assertNotIn("refuse", label["alt"],
                             f"{cid}: refuse cannot be an alternative verdict")
        # 187451a0 is the bot-state case: 'plan' is the reading taken, but an
        # honest clarify is also defensible, so it is recorded and scored.
        amb = [l for l in got.values() if l["alt"]]
        for label in amb:
            self.assertTrue(label["why"], "an alternative without a why is a guess")


if __name__ == "__main__":
    unittest.main()

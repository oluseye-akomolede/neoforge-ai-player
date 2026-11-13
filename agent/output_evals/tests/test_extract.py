"""Tests for extraction: the joins, the era split, and the two honesty rules.

Fixtures are written in the shape `agent/trajectory_log.py` produces, because
the earlier defect in this rig was fixtures that agreed with the reader instead
of with the producer.
"""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
for p in (REPO, os.path.join(REPO, "agent")):
    if p not in sys.path:
        sys.path.insert(0, p)

from output_evals import extract  # noqa: E402

CURRENT = "qwen3-coder:30b"
OLD = "qwen2.5-coder:32b"


def call(cid, phase, model=CURRENT, plan_ref="p1", bot="scout", response="{}"):
    return {"type": "call", "call_id": cid, "ts": "2026-11-13T10:00:00",
            "phase": phase, "bot": bot, "model": model, "plan_ref": plan_ref,
            "subtask_id": 1, "prompt_system": "sys", "prompt_user": "user",
            "response_raw": response, "parsed": None, "parse_error": None,
            "world_state_summary": "state"}


def outcome(cid, satisfied=True):
    return {"type": "outcome", "call_id": cid, "ts": "2026-11-13T10:01:00",
            "phase": "exec", "bot": "scout", "satisfied": satisfied,
            "strategy": "criteria", "reason": "ok"}


def plan_close(ref, status="complete"):
    return {"type": "plan_close", "ts": "2026-11-13T10:02:00", "bot": "scout",
            "plan_ref": ref, "status": status, "task": "t",
            "subtasks_total": 2, "subtasks_complete": 2}


class JoinTests(unittest.TestCase):
    def test_exec_joins_outcome_on_call_id(self):
        cases, census = extract.build_cases([call("c1", "exec"), outcome("c1")])
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].label, "satisfied")
        self.assertEqual(cases[0].label_source, "outcome")
        self.assertEqual(census.joined["exec"], 1)

    def test_unsatisfied_outcome_is_a_label_not_absence(self):
        cases, _ = extract.build_cases([call("c1", "exec"), outcome("c1", False)])
        self.assertEqual(cases[0].label, "unsatisfied")

    def test_exec_without_outcome_is_no_label(self):
        cases, census = extract.build_cases([call("c1", "exec")])
        self.assertEqual(cases, [])
        self.assertEqual(census.no_label["exec"], 1)

    def test_plan_joins_plan_close_on_plan_ref(self):
        cases, census = extract.build_cases([call("c1", "plan"), plan_close("p1")])
        self.assertEqual(cases[0].label, "complete")
        self.assertEqual(cases[0].label_source, "plan_close")
        self.assertEqual(census.joined["plan"], 1)

    def test_incomplete_plan_close_labels_incomplete(self):
        cases, _ = extract.build_cases([call("c1", "plan"), plan_close("p1", "abandoned")])
        self.assertEqual(cases[0].label, "incomplete")

    def test_replan_uses_its_own_plan_ref(self):
        recs = [call("c1", "replan", plan_ref="p7"), plan_close("p7")]
        cases, _ = extract.build_cases(recs)
        self.assertEqual(cases[0].label, "complete")

    def test_unjoined_plan_is_counted_not_scored(self):
        cases, census = extract.build_cases([call("c1", "plan"), plan_close("other")])
        self.assertEqual(cases, [])
        self.assertEqual(census.no_label["plan"], 1)


class CensusTests(unittest.TestCase):
    def test_era_split_counts_calls_and_labelled(self):
        recs = [call("c1", "replan", model=OLD, plan_ref="a"),
                call("c2", "replan", model=OLD, plan_ref="b"),
                call("c3", "replan", plan_ref="c"),
                plan_close("a"), plan_close("c")]
        _, census = extract.build_cases(recs)
        era = census.by_era["replan"]
        self.assertEqual(era[OLD]["calls"], 2)
        self.assertEqual(era[OLD]["labelled"], 1)
        self.assertEqual(era[CURRENT]["calls"], 1)
        self.assertEqual(era[CURRENT]["labelled"], 1)

    def test_report_states_shortfall(self):
        recs = [call(f"c{i}", "replan", plan_ref=f"p{i}") for i in range(21)]
        recs += [plan_close(f"p{i}") for i in range(21)]
        _, census = extract.build_cases(recs)
        rep = census.report()
        self.assertEqual(rep["kinds"]["replan"]["labelled"], 21)
        self.assertEqual(rep["kinds"]["replan"]["short_of_30"], 9)

    def test_distinct_days(self):
        recs = [call("c1", "exec")]
        recs[0]["ts"] = "2026-08-14T01:00:00"
        recs.append({**call("c2", "exec"), "ts": "2026-11-13T01:00:00"})
        _, census = extract.build_cases(recs)
        self.assertEqual(len(census.days), 2)


class SamplingTests(unittest.TestCase):
    def _pool(self, n_current, n_old):
        cases = []
        for i in range(n_current):
            cases.append(extract.Case("replan", f"c{i}", "scout", CURRENT, "", "", "", "{}", "complete", "plan_close"))
        for i in range(n_old):
            cases.append(extract.Case("replan", f"o{i}", "scout", OLD, "", "", "", "{}", "complete", "plan_close"))
        return cases

    def test_current_era_taken_first(self):
        taken, tally = extract.take_era_first(self._pool(21, 250), CURRENT)
        self.assertEqual(len(taken), 30)
        self.assertEqual(tally[CURRENT], 21)
        self.assertEqual(tally[OLD], 9)

    def test_no_padding_when_current_era_is_enough(self):
        taken, tally = extract.take_era_first(self._pool(37, 200), CURRENT)
        self.assertEqual(len(taken), 30)
        self.assertEqual(tally, {CURRENT: 30})

    def test_short_kind_is_not_invented(self):
        taken, tally = extract.take_era_first(self._pool(10, 3), CURRENT)
        self.assertEqual(len(taken), 13)   # 13 real cases, never 30
        self.assertEqual(tally[CURRENT] + tally[OLD], 13)

    def test_deterministic_for_same_input(self):
        pool = self._pool(40, 40)
        a, _ = extract.take_era_first(pool, CURRENT)
        b, _ = extract.take_era_first(pool, CURRENT)
        self.assertEqual([c.call_id for c in a], [c.call_id for c in b])

    def test_stratified_across_bots(self):
        cases = [extract.Case("exec", f"a{i}", "scout", CURRENT, "", "", "", "{}", "satisfied", "outcome")
                 for i in range(30)]
        cases += [extract.Case("exec", f"b{i}", "forge", CURRENT, "", "", "", "{}", "satisfied", "outcome")
                  for i in range(5)]
        taken, _ = extract.take_era_first(cases, CURRENT)
        bots = {c.bot for c in taken}
        self.assertEqual(bots, {"scout", "forge"}, "a busier bot must not take the whole sample")


class RedactionTests(unittest.TestCase):
    def test_bearer_token_redacted(self):
        out = extract.redact("Authorization: Bearer abcdefghijklmnop123456")
        self.assertNotIn("abcdefghijklmnop123456", out)

    def test_password_assignment_redacted(self):
        out = extract.redact("AIBOT_RCON_PASSWORD=hunter2hunter2")
        self.assertNotIn("hunter2hunter2", out)

    def test_long_blob_redacted(self):
        out = extract.redact("key " + "A" * 64)
        self.assertNotIn("A" * 64, out)

    def test_ordinary_text_untouched(self):
        text = "mine 3 iron ore near the village chest"
        self.assertEqual(extract.redact(text), text)


class DirTests(unittest.TestCase):
    def test_reads_all_daily_files_and_counts_bad_lines(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "trajectory-2026-11-12.jsonl"), "w") as f:
                f.write(json.dumps(call("c1", "exec")) + "\n")
            with open(os.path.join(d, "trajectory-2026-11-13.jsonl"), "w") as f:
                f.write(json.dumps(outcome("c1")) + "\n{not json\n")
            recs, bad = extract.read_records(d)
            self.assertEqual(len(recs), 2)
            self.assertEqual(bad, 1)
            cases, _ = extract.build_cases(recs)
            self.assertEqual(len(cases), 1)

    def test_missing_dir_raises(self):
        with self.assertRaises(FileNotFoundError):
            extract.read_records("/nonexistent/trajectories")

    def test_dir_from_env(self):
        old = os.environ.get("AIBOT_TRAJECTORY_DIR")
        try:
            os.environ["AIBOT_TRAJECTORY_DIR"] = "/tmp/x"
            self.assertEqual(str(extract.trajectory_dir()), "/tmp/x")
            del os.environ["AIBOT_TRAJECTORY_DIR"]
            with self.assertRaises(FileNotFoundError):
                extract.trajectory_dir()
        finally:
            if old is not None:
                os.environ["AIBOT_TRAJECTORY_DIR"] = old


if __name__ == "__main__":
    unittest.main()

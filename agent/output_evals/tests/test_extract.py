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

    def test_exec_without_outcome_is_still_a_replay_case(self):
        """A replay scores a NEW output, so it needs only a usable input.

        The recorded outcome is irrelevant to whether the call can be replayed.
        Requiring one dropped every call the corpus has no outcome for -- all
        the current-era exec calls without one -- from the replay pool.
        """
        cases, census = extract.build_cases([call("c1", "exec")])
        self.assertEqual(len(cases), 1, "an unlabelled call is still replayable")
        self.assertEqual(cases[0].label, "", "no recorded outcome, no label")
        self.assertEqual(census.replayable["exec"], 1)
        self.assertEqual(census.no_label["exec"], 1, "still counted as unlabelled")
        self.assertEqual(census.joined["exec"], 0)

    def test_plan_joins_plan_close_on_plan_ref(self):
        cases, census = extract.build_cases([call("c1", "plan"), plan_close("p1")])
        self.assertEqual(cases[0].label, "complete")
        self.assertEqual(cases[0].label_source, "plan_close")
        self.assertEqual(census.joined["plan"], 1)

    def test_incomplete_plan_close_labels_incomplete(self):
        cases, _ = extract.build_cases([call("c1", "plan"), plan_close("p1", "failed")])
        self.assertEqual(cases[0].label, "incomplete")

    def test_cancelled_plan_is_not_a_model_failure(self):
        # The corpus carries statuses complete/failed/cancelled. A cancelled
        # run was abandoned, not failed; scoring it incomplete charges the
        # model for a decision it did not make. It leaves the LABEL rate and
        # gets its own counter.
        #
        # It is still REPLAYABLE: a replay re-sends the recorded input and
        # scores a fresh output, so the old verdict is irrelevant. Excluding it
        # from the pool silently shrank the current-era plan sample 37 -> 31.
        cases, census = extract.build_cases([call("c1", "plan"), plan_close("p1", "cancelled")])
        self.assertEqual(len(cases), 1, "cancelled is still a replay case")
        self.assertEqual(cases[0].label, "")
        self.assertEqual(census.cancelled["plan"], 1)
        self.assertEqual(census.joined["plan"], 0)
        self.assertEqual(census.replayable["plan"], 1)
        self.assertEqual(census.report()["kinds"]["plan"]["cancelled"], 1)
        # The census must still account for the plan exactly once. Without this
        # the cancelled plan is ALSO counted as no_label, and the three buckets
        # stop summing to the call count -- which is how the double count would
        # otherwise reach a report unnoticed.
        self.assertEqual(census.no_label["plan"], 0)
        row = census.report()["kinds"]["plan"]
        self.assertEqual(row["labelled"] + row["no_label"] + row["cancelled"],
                         row["calls"])

    def test_census_buckets_sum_to_calls_for_every_kind(self):
        """labelled + no_label + cancelled == calls, per kind, on mixed input."""
        recs = []
        for i in range(4):                      # exec: 2 labelled, 2 not
            recs.append(call(f"e{i}", "exec"))
            if i < 2:
                recs.append({"type": "outcome", "call_id": f"e{i}", "satisfied": True})
        for i in range(3):                      # plan: 1 complete, 1 cancelled, 1 none
            recs.append(call(f"p{i}", "plan", plan_ref=f"P{i}"))
        recs.append(plan_close("P0", "complete"))
        recs.append(plan_close("P1", "cancelled"))
        _, census = extract.build_cases(recs)
        for kind, row in census.report()["kinds"].items():
            self.assertEqual(
                row["labelled"] + row["no_label"] + row["cancelled"], row["calls"],
                f"{kind}: buckets do not sum to calls ({row})")

    def test_replan_uses_its_own_plan_ref(self):
        recs = [call("c1", "replan", plan_ref="p7"), plan_close("p7")]
        cases, _ = extract.build_cases(recs)
        self.assertEqual(cases[0].label, "complete")

    def test_unjoined_plan_is_replayable_but_unlabelled(self):
        cases, census = extract.build_cases([call("c1", "plan"), plan_close("other")])
        self.assertEqual(len(cases), 1, "replay does not need the plan_close join")
        self.assertEqual(cases[0].label, "")
        self.assertEqual(census.no_label["plan"], 1)
        self.assertEqual(census.replayable["plan"], 1)


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
        _, census = extract.build_cases(recs, current_era=CURRENT)
        rep = census.report()
        self.assertEqual(rep["kinds"]["replan"]["labelled"], 21)
        self.assertEqual(rep["kinds"]["replan"]["short_of_30"], 9)

    def test_shortfall_is_measured_against_the_current_era_not_all_eras(self):
        """replan: 21 today, 50 older. The spec's shortfall is the CURRENT era's.

        An all-era measure prints 0 here and hides the shortfall the precedence
        paragraph is about -- the number the owner reads Friday.
        """
        recs = [call(f"c{i}", "replan", plan_ref=f"p{i}") for i in range(21)]
        recs += [call(f"o{i}", "replan", model=OLD, plan_ref=f"q{i}") for i in range(50)]
        _, census = extract.build_cases(recs, current_era=CURRENT)
        rep = census.report()["kinds"]["replan"]
        self.assertEqual(rep["short_of_30"], 9, "current era: 21 -> 9 short")
        self.assertEqual(rep["short_of_30_all_era"], 0, "all eras: 71 -> not short")

    def test_shortfall_without_a_named_era_counts_nothing_as_current(self):
        """No current_era -> the era measure is unknown, not silently all-era."""
        recs = [call(f"c{i}", "replan", plan_ref=f"p{i}") for i in range(21)]
        _, census = extract.build_cases(recs)
        rep = census.report()["kinds"]["replan"]
        self.assertEqual(rep["short_of_30"], 30)
        self.assertEqual(rep["short_of_30_all_era"], 9)

    def test_historical_plan_score_is_plan_close_status(self):
        """plan_close.status IS the plan-level verdict, joined on plan_ref.

        The lead corrected my reading here: satisfied/strategy/reason being
        null on plan_close rows does not mean no verdict exists -- status is
        the verdict. Cancelled leaves the rate; it is not a planner failure.
        """
        recs = [call("c1", "plan", plan_ref="a"), plan_close("a", "complete"),
                call("c2", "plan", plan_ref="b"), plan_close("b", "failed"),
                call("c3", "plan", plan_ref="c"), plan_close("c", "cancelled")]
        _, census = extract.build_cases(recs)
        h = census.report()["kinds"]["plan"]["historical"]
        self.assertEqual(h["counts"].get("complete"), 1)
        self.assertEqual(h["counts"].get("incomplete"), 1)
        self.assertEqual(h["n"], 2, "cancelled is excluded from the rate")
        self.assertAlmostEqual(h["rate"], 0.5)
        self.assertEqual(h["attribution"], "plan_close.status on plan_ref")

    def test_historical_exec_score_is_outcome_satisfied(self):
        recs = [call("c1", "exec"), outcome("c1", True),
                call("c2", "exec"), outcome("c2", False)]
        _, census = extract.build_cases(recs)
        h = census.report()["kinds"]["exec"]["historical"]
        self.assertEqual(h["n"], 2)
        self.assertAlmostEqual(h["rate"], 0.5)
        self.assertEqual(h["attribution"], "outcome.satisfied on call_id")

    def test_corpus_wide_plan_close_status_is_reported_separately(self):
        """Two denominators: closures joinable to a call, and closure rows.

        A closure whose plan_ref no call carries is not attributable to a
        case, so it cannot be in the historical n -- but its row still exists
        and the report must say so, or the two figures read as a discrepancy.
        """
        recs = [call("c1", "plan", plan_ref="a"), plan_close("a", "complete"),
                plan_close("orphan", "failed")]      # no call carries 'orphan'
        _, census = extract.build_cases(recs)
        rep = census.report()
        self.assertEqual(rep["kinds"]["plan"]["historical"]["n"], 1)
        self.assertEqual(rep["plan_close_status"].get("failed"), 1,
                         "the orphan closure is still counted corpus-wide")
        self.assertEqual(rep["plan_closes"], 2)

    def test_shortfall_measures_the_n_actually_run(self):
        """At n=25 a current-era pool of 21 is 4 short, not 9.

        The shortfall is only meaningful against the n that ran.
        """
        recs = [call(f"c{i}", "replan", plan_ref=f"p{i}") for i in range(21)]
        _, census = extract.build_cases(recs, current_era=CURRENT, per_kind=25)
        rep = census.report()["kinds"]["replan"]
        self.assertEqual(rep["short_of_25"], 4)
        self.assertNotIn("short_of_30", rep)

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


class CaseSetRoundTripTests(unittest.TestCase):
    """write_cases -> read_cases_dir must preserve every field.

    The scoring Job reads its cases through a ConfigMap and never sees the
    corpus, so a field dropped in the round trip is a field the scorer silently
    loses. Written and read in the same test so the pair cannot drift.
    """

    def test_round_trip_preserves_every_field(self):
        cases, _ = extract.build_cases([call("c1", "plan"), plan_close("p1")])
        with tempfile.TemporaryDirectory() as d:
            extract.write_cases({"plan": cases}, d)
            back = extract.read_cases_dir(d)
        self.assertEqual(back["plan"], cases)

    def test_missing_kind_is_absent_not_invented(self):
        # A kind the corpus could not supply must not appear as an empty list
        # that a report could read as "scored zero".
        cases, _ = extract.build_cases([call("c1", "plan"), plan_close("p1")])
        with tempfile.TemporaryDirectory() as d:
            extract.write_cases({"plan": cases}, d)
            back = extract.read_cases_dir(d)
        self.assertIn("plan", back)
        self.assertNotIn("exec", back)

    def test_unknown_dir_refuses(self):
        with self.assertRaises(FileNotFoundError):
            extract.read_cases_dir("/nonexistent-cases-dir")


if __name__ == "__main__":
    unittest.main()

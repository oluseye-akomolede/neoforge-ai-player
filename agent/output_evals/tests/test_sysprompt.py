"""The rebuild-from-source leg: the text SENT equals the CURRENT source prompt.

The lead's requirement, stated once: "Include a test proving that the text
sent equals the source prompt." So these tests go through the byte the wire
carries -- `run.ask` -- rather than calling `sysprompt.rebuild` and comparing
the result to itself, which would pass even if run.py never used it.
"""
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve()
AGENT = HERE.parents[2]                      # .../agent
sys.path.insert(0, str(AGENT))

import l3_planner                              # noqa: E402
from output_evals import extract, run as runmod, sysprompt   # noqa: E402


def norm(text):
    """Collapse line wraps so the comparison is of text, not of layout."""
    return " ".join(text.split())

# A recorded plan prompt carrying only the two sections the rebuild reads back.
# The rebuild must recover these from the record rather than substituting
# defaults, so the fixture has to contain them: an empty string is the
# "unscorable" case, tested separately.
RECORDED_PLAN_PROMPT = (
    "You are {bot}, an AI bot in Minecraft.\n"
    "Available dimensions on this server (you can subtask any of these; use exact ids):\n"
    "  - minecraft:overworld\n"
    "  - minecraft:the_end\n"
    "Registered skills (each runs end-to-end as ONE deterministic directive):\n"
    "  - mine: Dig a block.  [params: x:int]\n"
)


def plan_case(**kw):
    base = dict(kind="plan", call_id="c1", bot="scout", model="m",
                prompt_system=RECORDED_PLAN_PROMPT.format(bot="scout"),
                prompt_user="store my stuff",
                world_state_summary="", recorded_output="{}",
                label="", label_source="")
    base.update(kw)
    return extract.Case(**base)


class RebuiltTextIsWhatGetsSent(unittest.TestCase):
    def test_plan_prompt_sent_equals_the_source_prompt(self):
        """Not "the rebuild is stable" -- the bytes on the wire.

        The format arguments are read off call_plan's own call site, so if
        either side is edited without the other this fails rather than
        drifting quietly. Compared whitespace-normalised: `_norm` in the
        prompt-text tests collapses line wraps, and the same text with one
        wrap moved is the same text.
        """
        case = plan_case()
        with mock.patch.object(runmod, "ask", return_value=('{"ok":1}', None)) as sent:
            sysprompt.rebuild(case, l3_planner)
            runmod.run(_cfg(), {"plan": [case]}, log=lambda *_: None)
        system, user = sent.call_args[0][1], sent.call_args[0][2]
        self.assertEqual(user, "store my stuff")
        # The source prompt, formatted exactly as l3_planner:418 does it.
        expected = l3_planner._PLAN_SYSTEM_PROMPT.format(
            bot_name="scout",
            persona=l3_planner.BOT_PERSONAS.get("scout", "generalist"),
            dimensions=l3_planner._dim_lines(
                ["minecraft:overworld", "minecraft:the_end"]),
            skills="  - mine: Dig a block.  [params: x:int]",
        )
        self.assertEqual(norm(system), norm(expected))
        self.assertIn(norm("If no prerequisite path can deliver the stated goal"),
                      norm(system))

    def test_the_rebuilt_text_is_the_CURRENT_prompt_not_a_frozen_one(self):
        """A change to the source prompt must reach the wire.

        Run against a mutated module attribute, which is the only way to show
        the wire text is derived rather than a copy of whatever the test
        expected when it was written.
        """
        case = plan_case()
        with mock.patch.object(l3_planner, "_PLAN_SYSTEM_PROMPT",
                               "MUTANT {bot_name}|{persona}|{dimensions}|{skills}"), \
             mock.patch.object(runmod, "ask", return_value=('{}', None)) as sent:
            sysprompt.rebuild(case, l3_planner)
            runmod.run(_cfg(), {"plan": [case]}, log=lambda *_: None)
        self.assertTrue(sent.call_args[0][1].startswith("MUTANT scout|"))


class ValuesComeFromTheRecord(unittest.TestCase):
    def test_missing_user_prompt_is_unscorable_not_guessed(self):
        case = plan_case(prompt_user="")
        with self.assertRaises(sysprompt.Unscorable):
            sysprompt.rebuild(case, l3_planner)

    def test_missing_bot_is_unscorable(self):
        with self.assertRaises(sysprompt.Unscorable):
            sysprompt.rebuild(plan_case(bot=""), l3_planner)

    def test_replan_without_recorded_plan_is_unscorable(self):
        """The `synthesised` source carries a hand-written response and no plan.

        There is nothing honest to format into {plan_json}/{subtask_json}, so
        the case is refused rather than rebuilt with an empty object.
        """
        case = extract.Case(kind="replan", call_id="r1", bot="scout", model="m",
                            prompt_system="", prompt_user="Revise the failed subtask.",
                            world_state_summary="",
                            recorded_output=json.dumps({"id": 1, "description": "d",
                                                        "criteria": "c"}),
                            label="", label_source="", source="synthesised")
        with self.assertRaises(sysprompt.Unscorable) as cm:
            sysprompt.rebuild(case, l3_planner)
        self.assertIn("source=synthesised", str(cm.exception))

    def test_replan_rebuilds_from_the_recorded_plan_and_subtask(self):
        plan = {"task": "store my stuff", "bot": "scout",
                "created_at": "2026-11-15T00:00:00", "status": "executing",
                "subtasks": [{"id": 1, "description": "carry it", "criteria": "c",
                              "status": "failed", "attempts": 2, "error": "no room"}],
                "current_subtask_id": 1}
        case = extract.Case(kind="replan", call_id="r2", bot="scout", model="m",
                            prompt_system="", prompt_user="Revise the failed subtask.",
                            world_state_summary="",
                            recorded_output=json.dumps({"id": 1, "description": "d",
                                                        "criteria": "c"}),
                            label="", label_source="", source="iface",
                            recorded_plan=plan, recorded_subtask=plan["subtasks"][0])
        sysprompt.rebuild(case, l3_planner)
        self.assertIn("no room", case.prompt_system)
        self.assertIn('"attempts": 2', case.prompt_system)
        self.assertNotIn('"error": "<short reason>"', case.prompt_system)

    def test_a_brace_inside_a_criteria_does_not_truncate_the_plan(self):
        """F2: `criteria` is free text and can contain a brace.

        Every other fixture here uses "c", so a mutant that returns at the
        first `}` instead of counting braces passes all of them. That mutant
        truncates the recovered plan at the first brace in a string and the
        case silently rebuilds against a fragment.

        A criteria like "chest holds {16} wheat" is not exotic: item counts in
        braces are how a bot is told to check an inventory.

        The plan must come ONLY from the prompt text: passing recorded_plan
        takes the shortcut and never reaches the scanner, which is how this
        went untested through 14 fixtures.
        """
        plan = {"task": "store my stuff", "bot": "scout",
                "created_at": "2026-11-15T00:00:00", "status": "executing",
                "subtasks": [{"id": 1, "description": "fill the chest",
                              "criteria": "chest has {16} wheat",
                              "status": "failed", "attempts": 2, "error": "full"}],
                "current_subtask_id": 1}
        # The heads _from_recorded_prompt scans for, spelled as it spells them.
        recorded = ("Full plan: " + json.dumps(plan) + "\n"
                    "Failed subtask: " + json.dumps(plan["subtasks"][0]))
        case = extract.Case(kind="replan", call_id="r3", bot="scout", model="m",
                            prompt_system="",
                            prompt_user="Revise the failed subtask.",
                            world_state_summary="",
                            recorded_output=json.dumps({"id": 1, "description": "d",
                                                        "criteria": "chest has {16} wheat"}),
                            label="", label_source="", source="iface")
        case.recorded_prompt_system = recorded
        sysprompt.rebuild(case, l3_planner)
        # The marker AFTER the brace is what a first-`}` mutant loses.
        self.assertIn("attempts", case.prompt_system)
        self.assertIn("full", case.prompt_system)

    def test_balanced_object_counts_braces_inside_strings(self):
        """Direct unit test of the scanner, not through a rebuild.

        Pins the property the module docstring claims: a greedy or
        first-brace cut is wrong on nested objects and on braces in strings.
        """
        text = 'noise {"a": {"inner": 1}, "b": "has } and { braces"} tail'
        start = text.index("{")
        self.assertEqual(json.loads(sysprompt._balanced_object(text, start)),
                         {"a": {"inner": 1}, "b": "has } and { braces"})


class UnscorableIsNotAPass(unittest.TestCase):
    def test_an_unscorable_case_is_never_sent(self):
        """Marked unscorable => not sent, and counted unscorable.

        Sending the recorded prompt instead would answer a different question
        from the rest of the run and print the result under the same heading.
        """
        case = plan_case(prompt_user="")
        try:
            sysprompt.rebuild(case, l3_planner)
        except sysprompt.Unscorable as e:
            case.prompt_diff = f"unscorable: {e}"
        with mock.patch.object(runmod, "ask", return_value=('{"ok":1}', None)) as sent:
            results = runmod.run(_cfg(), {"plan": [case]}, log=lambda *_: None,
                                 rebuild_applied=True)
        self.assertFalse(sent.called)
        self.assertEqual(results["plan"]["unscorable"], 1)
        self.assertEqual(results["plan"]["pass"], 0)

    def test_an_empty_recorded_prompt_is_not_comparable(self):
        """False would be a claim; there is nothing to compare it to."""
        differs, how = sysprompt.differs(plan_case(), "x" * 500, "")
        self.assertIsNone(differs)
        self.assertIn("not-comparable", how)


def _cfg():
    from output_evals.evalconfig import Config
    return Config(endpoint="http://unused", model="m", timeout=1, concurrency=1,
                  path="test", raw={}, think=False, endpoint_from_env=False,
                  think_from_file=False)


if __name__ == "__main__":
    unittest.main()


class SkillsCatalogComesFromTheRecord(unittest.TestCase):
    """An unset EVALS_SKILLS_FILE must not blank the catalog.

    `skills_from_env()` returns "" when unset, and rebuild() only falls back to
    the recorded catalog on None. So a caller passing "" straight through
    rebuilds every plan prompt with no skills at all -- a prompt the model was
    never shown, scored as if it were the current one. Production hit this on
    the first run with the flag on; it is the reason this test exists.
    """

    def test_rebuild_falls_back_to_the_record_when_skills_is_unset(self):
        case = plan_case()
        sysprompt.rebuild(case, l3_planner, skills=None)
        self.assertIn("Registered skills", case.prompt_system)
        self.assertIn("mine: Dig a block", case.prompt_system)

    def test_an_explicit_empty_string_is_honoured(self):
        """"" is a real shape -- `_skills_lines()` when the API is down.

        The defect was run.py CONVERTING unset into "", not rebuild() treating
        "" as a value. So passing "" on purpose must still produce the
        API-down prompt; the fallback belongs to the caller.
        """
        case = plan_case()
        sysprompt.rebuild(case, l3_planner, skills="")
        self.assertNotIn("mine: Dig a block", case.prompt_system)

    def test_a_missing_skills_section_is_unscorable_not_empty(self):
        case = plan_case(prompt_system="You are scout.\nAvailable dimensions:\n"
                                      "  - minecraft:overworld\n")
        with self.assertRaises(sysprompt.Unscorable):
            sysprompt.rebuild(case, l3_planner)


class RebuildIsOptIn(unittest.TestCase):
    def test_dry_run_without_the_flag_leaves_the_recorded_prompt(self):
        """The flag must be opt-in: the scoring path is unchanged when off."""
        case = plan_case()
        before = case.prompt_system
        runmod.run(_cfg(), {"plan": [case]}, log=lambda *_: None)
        self.assertEqual(case.prompt_system, before)
        self.assertEqual(case.recorded_prompt_system, "")


class TheJobRebuildsFromItsOwnCodeConfigMap(unittest.TestCase):
    """The lead's condition: both legs share ONE case ConfigMap.

    So the case set must not contain a rendered prompt -- if it did, the
    "before" leg would replay the "after" leg's text and the comparison would
    be of the code ConfigMap against itself. The rebuild has to happen inside
    the Job. These drive main(), which is the path the Job actually runs.
    """

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        (self.tmp / "cases" / "rebuild").mkdir(parents=True)
        (self.tmp / "cfg.yaml").write_text("endpoint: http://unused\nmodel: m\n"
                                           "timeout: 1\n", encoding="utf-8")
        # A case as the case ConfigMap would carry it: the recorded prompt is
        # present as the rebuild's INPUT, and prompt_system is empty.
        row = plan_case().__dict__.copy()
        row["recorded_prompt_system"] = RECORDED_PLAN_PROMPT.format(bot="scout")
        row["prompt_system"] = ""
        (self.tmp / "cases" / "rebuild" / "plan.jsonl").write_text(
            json.dumps(row) + "\n", encoding="utf-8")

    def _main(self, argv):
        # main() loads the config from disk and checks the endpoint; both are
        # replaced so the test drives the CASES path, not the network.
        with mock.patch.object(runmod, "ask", return_value=('{"ok":1}', None)) as sent, \
             mock.patch.object(runmod.evalconfig, "load_config", return_value=_cfg()), \
             mock.patch.object(runmod.evalconfig, "check_endpoint",
                        return_value=(True, "stubbed")):
            with mock.patch.object(sys, "argv", ["run.py"] + argv):
                rc = runmod.main()
        return rc, sent

    def test_an_empty_prompt_in_the_case_set_is_rebuilt_from_the_imported_module(self):
        # NOT --dry-run: dry-run returns before run(), so it makes no model
        # calls and there is no `ask` invocation to inspect. The endpoint is
        # stubbed in _main, so the real scoring path runs with no network.
        rc, sent = self._main([
            "--config", str(self.tmp / "cfg.yaml"),
            "--cases-in", str(self.tmp / "cases"),
            "--rebuild-from-source",
            "--out", str(self.tmp / "r.json"),
        ])
        self.assertEqual(rc, 0)
        system = sent.call_args[0][1]
        self.assertIn(norm("If no prerequisite path can deliver the stated goal"),
                      norm(system))

    def test_without_the_flag_the_run_fails_closed(self):
        """Fail closed: no rebuild means no prompt, and that must not score.

        The case's prompt is empty until the rebuild fills it. Scoring it
        unrebuilt measures the model against nothing and records a verdict,
        and nothing in the report would show it -- `rebuild_applied` is False
        precisely when the skip guard is off.

        NOT --dry-run: dry-run returns before run(), so an earlier version of
        this test asserted on a call that never happened and passed while
        proving nothing.
        """
        rc, sent = self._main([
            "--config", str(self.tmp / "cfg.yaml"),
            "--cases-in", str(self.tmp / "cases"),
            "--out", str(self.tmp / "r.json"),
        ])
        self.assertEqual(rc, 5, "an unrebuilt plan case must exit non-zero")
        self.assertIsNone(sent.call_args,
                          "the empty prompt must never reach the model")
        self.assertFalse((self.tmp / "r.json").exists(),
                         "a refused run must not leave a report behind")

    def test_the_flag_makes_the_same_case_scoreable(self):
        """The other direction: same case set, flag on, it runs."""
        rc, sent = self._main([
            "--config", str(self.tmp / "cfg.yaml"),
            "--cases-in", str(self.tmp / "cases"),
            "--rebuild-from-source",
            "--out", str(self.tmp / "r.json"),
        ])
        self.assertEqual(rc, 0)
        self.assertIsNotNone(sent.call_args)
        self.assertGreater(len(sent.call_args[0][1]), 1000)

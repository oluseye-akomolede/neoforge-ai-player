"""Unit tests for the planner scorers.

Every test names the output shape it scores and the failure it would catch. The
two fail-closed tests matter most: an unreadable surface and an unlabelled case
must not produce a pass.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
for p in (REPO, os.path.join(REPO, "agent")):
    if p not in sys.path:
        sys.path.insert(0, p)

from output_evals.scorers import common, planner  # noqa: E402


def j(obj):
    return json.dumps(obj)


class SurfaceTests(unittest.TestCase):
    def setUp(self):
        planner.reset_surface_cache()

    def test_surface_loads_from_action_binding(self):
        surface, err = planner._load_surface()
        self.assertEqual(err, "")
        self.assertIn("STORE_ALL", surface)
        self.assertIn("EQUIP", surface)  # agent-side kind is bindable too

    def test_unreadable_surface_is_unscorable_not_pass(self):
        # The failure this guards: a surface that cannot be read must not
        # vouch. Drive the branch directly -- monkeypatching the module from
        # the test is fragile (it imports agent.py, which needs psycopg2).
        plan = j({"task": "t", "subtasks": [{"id": 1, "description": "d",
                                           "criteria": "c",
                                           "directives": [{"kind": "MINE"}]}]})
        self.assertTrue(planner.score_plan(plan).ok)
        original = planner._load_surface
        try:
            planner._load_surface = lambda: (None, "surface unavailable")
            r = planner.score_plan(plan)
            self.assertEqual(r.verdict, common.UNSCORABLE,
                             "a surface that cannot be read must not vouch")
            self.assertFalse(r.ok)
            self.assertEqual(planner.score_exec(j({"directives": [{"kind": "MINE"}]})).verdict,
                             common.UNSCORABLE)
        finally:
            planner._load_surface = original
            planner.reset_surface_cache()


class ExecTests(unittest.TestCase):
    def test_valid_directives_pass(self):
        r = planner.score_exec(j({"directives": [{"kind": "STORE_ALL",
                                                  "target": "chest"}]}))
        self.assertTrue(r.ok, r.reason)

    def test_empty_list_fails(self):
        self.assertFalse(planner.score_exec(j({"directives": []})).ok)

    def test_unknown_kind_fails(self):
        r = planner.score_exec(j({"directives": [{"kind": "TELEPORT_HOME"}]}))
        self.assertEqual(r.verdict, common.FAIL)
        self.assertIn("not in the allowed surface", r.reason)

    def test_param_outside_surface_fails(self):
        r = planner.score_exec(j({"directives": [{"kind": "MINE",
                                                  "inventory": {"x": 1}}]}))
        self.assertEqual(r.verdict, common.FAIL)
        self.assertIn("inventory", r.reason)

    def test_fenced_json_is_unwrapped(self):
        body = j({"directives": [{"kind": "GOTO", "x": 1, "y": 64, "z": 2}]})
        self.assertTrue(planner.score_exec("```json\n" + body + "\n```").ok)

    def test_non_json_fails(self):
        self.assertFalse(planner.score_exec("I will go mine some iron").ok)

    def test_empty_output_fails(self):
        self.assertFalse(planner.score_exec("").ok)

    def test_allowed_param_passes(self):
        r = planner.score_exec(j({"directives": [{"kind": "MINE",
                                                  "count": 3, "extra": {}}]}))
        self.assertTrue(r.ok, r.reason)

    def test_skill_is_the_preferred_answer_not_an_off_surface_kind(self):
        """The model is ASKED for SKILL, so passing it is correct scoring.

        l3_planner.py:517 (EXEC prompt): "emit exactly ONE directive of kind
        SKILL". Its worked example at :534 is this exact shape, and the prompt
        calls a matching skill "always the better choice". plan_orchestrator.py
        :1056 executes a model-emitted SKILL and mod DirectiveType.java:33
        declares it. SKILL is absent from BINDABLE_KINDS on purpose -- whether
        the binder accepts it is a separate question from whether the model was
        right to say it, and this scorer answers the second.
        """
        r = planner.score_exec(j({"directives": [
            {"kind": "SKILL", "target": "mine_and_smelt",
             "extra": {"target": "minecraft:iron_ore", "count": "8"}}]}))
        self.assertTrue(r.ok, r.reason)
        self.assertEqual(r.detail.get("skill"), 1)

    def test_skill_without_a_skill_id_fails(self):
        """Accepting the kind must not mean accepting an empty one."""
        for bad in ({"kind": "SKILL"}, {"kind": "SKILL", "target": ""},
                    {"kind": "SKILL", "target": "   "},
                    {"kind": "SKILL", "target": 7}):
            with self.subTest(bad=bad):
                r = planner.score_exec(j({"directives": [bad]}))
                self.assertEqual(r.verdict, common.FAIL)
                self.assertIn("skill id", r.reason)

    def test_skill_does_not_excuse_a_bad_sibling(self):
        """SKILL passing must not carry an off-surface kind along with it."""
        r = planner.score_exec(j({"directives": [
            {"kind": "SKILL", "target": "mine_and_smelt"},
            {"kind": "TELEPORT_HOME"}]}))
        self.assertEqual(r.verdict, common.FAIL)
        self.assertIn("TELEPORT_HOME", r.reason)

    def test_skill_passes_are_counted_in_the_detail(self):
        """Passes are visible per kind, not hidden inside an aggregate rate."""
        r = planner.score_exec(j({"directives": [
            {"kind": "SKILL", "target": "mine_and_smelt"},
            {"kind": "MINE", "count": 3}]}))
        self.assertTrue(r.ok, r.reason)
        self.assertEqual(r.detail.get("skill"), 1)
        self.assertEqual(r.detail.get("n"), 2)


class PlanTests(unittest.TestCase):
    def test_valid_plan_passes(self):
        plan = {"task": "get iron",
                "subtasks": [{"id": 1, "description": "mine", "criteria": "done",
                              "directives": [{"kind": "MINE", "count": 3}]}]}
        r = planner.score_plan(j(plan))
        self.assertTrue(r.ok, r.reason)

    def test_clarify_is_a_shape_not_a_pass_on_quality(self):
        r = planner.score_plan(j({"kind": "clarify", "reason": "which?"}))
        self.assertTrue(r.ok)
        self.assertEqual(r.detail.get("shape"), "clarify")

    def test_missing_criteria_fails(self):
        plan = {"task": "t", "subtasks": [{"id": 1, "description": "d"}]}
        r = planner.score_plan(j(plan))
        self.assertFalse(r.ok)
        self.assertIn("criteria", r.reason)

    def test_bad_kind_inside_a_subtask_fails(self):
        plan = {"task": "t",
                "subtasks": [{"id": 1, "description": "d", "criteria": "c",
                              "directives": [{"kind": "FROBNICATE"}]}]}
        r = planner.score_plan(j(plan))
        self.assertFalse(r.ok)
        self.assertIn("FROBNICATE", r.reason)

    def test_no_subtasks_fails(self):
        self.assertFalse(planner.score_plan(j({"task": "t",
                                               "subtasks": []})).ok)


class ReplanTests(unittest.TestCase):
    def test_flat_subtask_passes(self):
        r = planner.score_replan(j({"id": 2, "description": "try chest",
                                    "criteria": "has iron"}))
        self.assertTrue(r.ok, r.reason)

    def test_nested_subtask_passes(self):
        r = planner.score_replan(j({"subtask": {"id": 2, "description": "d",
                                                "criteria": "c"}}))
        self.assertTrue(r.ok, r.reason)

    def test_missing_description_fails(self):
        r = planner.score_replan(j({"id": 2, "criteria": "c"}))
        self.assertFalse(r.ok)
        self.assertIn("description", r.reason)


class KindSurfaceTests(unittest.TestCase):
    def test_empty_surface_is_an_error_not_a_pass(self):
        # The failure this guards: a surface read as empty would wave through
        # every kind, or reject every kind, depending on the branch.
        with self.assertRaises(ValueError):
            common.check_kind_surface([{"kind": "MINE"}], {})

    def test_none_surface_is_an_error(self):
        with self.assertRaises(ValueError):
            common.check_kind_surface([{"kind": "MINE"}], None)

    def test_unreadable_object_is_an_error(self):
        with self.assertRaises(ValueError):
            common.check_kind_surface([{"kind": "MINE"}], 42)


if __name__ == "__main__":
    unittest.main()

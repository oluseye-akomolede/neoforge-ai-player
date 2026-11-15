"""Pin the decline rules in the L3 planner prompts.

These assertions are deliberately about the prompt TEXT. The plan and replan
prompts are the whole product here: a model that never sees a rule cannot
follow it, and a rule quietly reworded or dropped is invisible to every other
test in the suite.
"""
import unittest

from l3_planner import _PLAN_SYSTEM_PROMPT, _REPLAN_SYSTEM_PROMPT


def _norm(text):
    """Collapse prompt line wraps so assertions test wording, not layout."""
    return " ".join(text.split())


class PlanPromptDeclineRules(unittest.TestCase):
    def test_transient_state_is_planned_around(self):
        text = _norm(_PLAN_SYSTEM_PROMPT)
        self.assertIn("precondition that does not hold YET", text)
        self.assertIn("empty inventory", text)
        self.assertIn("plan the prerequisite steps", text)

    def test_planning_around_is_not_substitution(self):
        """The distinction the requirement turns on.

        'Plan around an empty inventory' must mean fetch-then-deposit, not
        'find a nearby goal'. Without this the narrowed decline predicate
        licenses exactly the substitution spec.md:506 forbids.
        """
        text = _norm(_PLAN_SYSTEM_PROMPT)
        self.assertIn("adding prerequisite steps that still deliver the exact "
                      "goal asked for", text)
        self.assertIn("never swapping in a nearby goal", text)
        self.assertIn("If no prerequisite path can deliver the stated goal, "
                      "decline", text)

    def test_no_prerequisite_path_means_decline(self):
        """The rule must not become 'never refuse'.

        A world fact still refuses; the escape is only for states that can be
        changed.
        """
        text = _norm(_PLAN_SYSTEM_PROMPT)
        self.assertIn("you MUST decline", text)

    def test_correct_refusal_examples_survive(self):
        text = _norm(_PLAN_SYSTEM_PROMPT)
        self.assertIn("fly to the moon", text)
        self.assertIn("dig to bedrock at the same time", text)

    def test_clarify_examples_survive(self):
        text = _norm(_PLAN_SYSTEM_PROMPT)
        self.assertIn("go get some stuff", text)
        self.assertIn('"kind": "clarify"', text)

    def test_speech_is_not_a_directive(self):
        text = _norm(_PLAN_SYSTEM_PROMPT)
        self.assertIn("The bot can speak to the player", text)
        self.assertIn("NOT proof the bot cannot report an outcome", text)


class ReplanPromptContract(unittest.TestCase):
    def test_replan_demands_one_subtask(self):
        self.assertIn("You MUST return that one subtask object",
                      _norm(_REPLAN_SYSTEM_PROMPT))

    def test_replan_has_no_error_escape_hatch(self):
        """The invitation that produced all four replan eval failures.

        Adding back a line offering {"error": ...} would make the prompt
        disagree with the spec'd contract (a single replacement subtask) and
        would silently re-open the failure this change exists to fix.
        """
        text = _REPLAN_SYSTEM_PROMPT
        self.assertNotIn('"error"', text)
        self.assertNotIn("If truly impossible", text)

    def test_replan_still_pins_the_id(self):
        self.assertIn("id MUST equal", _REPLAN_SYSTEM_PROMPT)


class RefineSkillSiblingIsOutOfScope(unittest.TestCase):
    def test_refine_skill_still_has_its_own_hatch(self):
        """Records the known sibling deliberately left alone.

        _REFINE_SKILL_PROMPT carries a structurally identical {"error"}
        invitation. It is a different contract, so this change does not touch
        it -- but if someone later removes it, this test should be updated
        along with that change rather than failing silently in a diff.
        """
        from l3_planner import _REFINE_SKILL_PROMPT
        self.assertIn('"error"', _REFINE_SKILL_PROMPT)


if __name__ == "__main__":
    unittest.main()

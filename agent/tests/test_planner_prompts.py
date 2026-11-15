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
    """The plan prompt's decline rules are unchanged in this rev.

    The decline-precision rules from 5ee0406 are NOT here: the 11-15 eval run
    showed them turning bot state into world facts (plan 15 -> 12), so they
    were pulled back out to be reworked separately. What ships here is the
    replan fix alone, so the plan prompt is byte-identical to 9e656b3 and the
    only prompt that changed is the replan one. The remaining tests below pin
    the pre-existing clauses so the revert cannot quietly lose them either.
    """

    def test_correct_refusal_examples_survive(self):
        text = _norm(_PLAN_SYSTEM_PROMPT)
        self.assertIn("fly to the moon", text)
        self.assertIn("dig to bedrock at the same time", text)

    def test_clarify_examples_survive(self):
        text = _norm(_PLAN_SYSTEM_PROMPT)
        self.assertIn("go get some stuff", text)
        self.assertIn('"kind": "clarify"', text)

    def test_substitution_is_still_forbidden(self):
        text = _norm(_PLAN_SYSTEM_PROMPT)
        self.assertIn("a plausible substitution is still a lie", text)

    def test_the_reworked_rules_are_absent_from_this_rev(self):
        """Guards the split itself.

        If the plan rules creep back in without the rework that the 11-15 run
        showed is needed, this rev stops being 'replan alone' and becomes the
        regressing combination again.
        """
        text = _norm(_PLAN_SYSTEM_PROMPT)
        self.assertNotIn("Bot state is ALWAYS a precondition", text)
        self.assertNotIn("precondition that does not hold YET", text)


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

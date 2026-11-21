"""The script prompt names only kinds the binding accepts.

`SCRIPT_SURFACE` used to offer `"attack"` and `"place"` as examples. Neither is
in `BINDABLE_KINDS`, so a script that followed the prompt had its only action
refused and trial 4.1's tick spun on refusals. The rule these tests pin: the
prompt and the binding cannot drift, in either direction.
"""

from __future__ import annotations

import re
import unittest

import planner
from action_binding import BINDABLE_KINDS, RefusedAction, bind_action


def _example_kinds():
    """The kinds SCRIPT_SURFACE presents as valid: the named list plus the
    inline examples. Parsed from the rendered text, not from a literal here --
    a literal would agree with the prompt by construction and prove nothing."""
    surface = planner.SCRIPT_SURFACE
    found = set(re.findall(r'`"([A-Z][A-Z_]*)"`', surface))
    # The prompt also carries two negative examples ("there is no `"attack"`"),
    # which are lowercase and therefore not matched by the upper-case pattern.
    return found


class ScriptSurfaceKindTest(unittest.TestCase):

    def test_every_kind_the_prompt_shows_is_bindable(self):
        """KILLS: the shipped prompt offered "attack" and "place"."""
        shown = _example_kinds()
        self.assertTrue(shown, "no kinds parsed from SCRIPT_SURFACE -- the "
                               "pattern is wrong, so this test proves nothing")
        not_bindable = sorted(shown - BINDABLE_KINDS)
        self.assertEqual(
            [], not_bindable,
            f"the prompt offers kinds the binding refuses: {not_bindable}")

    def test_the_prompt_shows_every_bindable_kind(self):
        """The converse: a kind added to the binding must appear in the prompt,
        otherwise the prompt silently under-supplies the name and a model that
        would use it has to guess."""
        missing = sorted(BINDABLE_KINDS - _example_kinds())
        self.assertEqual([], missing, f"bindable but not named: {missing}")

    def test_the_stated_count_matches_the_binding(self):
        m = re.search(r"the (\d+) bindable kinds", planner.SCRIPT_SURFACE)
        self.assertIsNotNone(m, "the count sentence is gone or reworded")
        self.assertEqual(int(m.group(1)), len(BINDABLE_KINDS))

    def test_a_prompt_example_dispatches_without_refusal(self):
        """The end-to-end claim: what the prompt says, the binding accepts."""
        for kind in sorted(_example_kinds()):
            with self.subTest(kind=kind):
                bound = bind_action({"kind": kind})
                self.assertEqual(kind, bound["kind"])

    def test_lowercase_is_accepted_because_the_prompt_says_so(self):
        """The prompt now tells the model case does not matter; that promise
        must hold or the sentence is a new way to be refused."""
        self.assertEqual("MINE", bind_action({"kind": "mine"})["kind"])

    def test_the_invented_names_are_actually_refused(self):
        """The prompt names "attack" and "place" as WRONG. If one of them were
        ever added to the binding, the prompt would be lying about the present
        state, and this test says so at the point it happens."""
        for gone in ("attack", "place"):
            with self.subTest(kind=gone):
                with self.assertRaises(RefusedAction):
                    bind_action({"kind": gone})


class DriftTest(unittest.TestCase):
    """Removing a kind from BINDABLE_KINDS without touching the prompt reds.

    SCRIPT_SURFACE is computed at import from BINDABLE_KINDS, so the drift is
    simulated by shrinking the binding and re-importing -- which is what a real
    edit to action_binding.py does on the next process start. Patching the
    planner's already-imported name would prove nothing.
    """

    def test_removing_a_kind_from_the_binding_removes_it_from_the_prompt(self):
        import importlib
        import subprocess
        import sys
        import os

        here = os.path.dirname(os.path.abspath(__file__))
        probe = (
            "import action_binding, sys, planner\n"
            "assert '`\"MINE\"`' in planner.SCRIPT_SURFACE, 'not present before'\n"
            "sys.modules.pop('planner', None)\n"
            "action_binding.BINDABLE_KINDS = frozenset("
            "action_binding.BINDABLE_KINDS - {'MINE'})\n"
            "import planner\n"
            "assert '`\"MINE\"`' not in planner.SCRIPT_SURFACE, "
            "'MINE STILL IN PROMPT after removal -- a hand-written list drifted'\n"
            "n = len(action_binding.BINDABLE_KINDS)\n"
            "assert f'the {n} bindable kinds' in planner.SCRIPT_SURFACE\n"
            "print('DRIFT-OK')\n"
        )
        # A separate process because planner caches SCRIPT_SURFACE at import.
        out = subprocess.run([sys.executable, "-B", "-c", probe], cwd=here,
                             capture_output=True, text=True)
        self.assertEqual(0, out.returncode,
                         f"stdout={out.stdout!r} stderr={out.stderr[-800:]!r}")
        self.assertIn("DRIFT-OK", out.stdout)

    def test_the_examples_are_not_hand_written(self):
        """KILLS: an Examples line typed out, which is how "MINE" survived a
        binding that no longer had it. Every example must be a real kind."""
        m = re.search(r"Examples: (.*?)\. Matching", planner.SCRIPT_SURFACE)
        self.assertIsNotNone(m, "the Examples line is gone or reworded")
        examples = set(re.findall(r'`"([A-Z][A-Z_]*)"`', m.group(1)))
        self.assertEqual(4, len(examples), f"expected 4 examples, got {examples}")
        self.assertEqual(set(), examples - BINDABLE_KINDS,
                         "an example names a kind the binding refuses")


class LookupEntryFieldsTest(unittest.TestCase):
    """Task 4.5: the prompt must state the identity field of every lookup
    entry, and they DIFFER (block=id, mob=type, item=item). KILLS: documenting
    one shape and leaving a script to guess `id` for the other two, which
    reads `undefined` and looks like an empty result."""

    def test_each_lookup_shape_names_its_identity_field(self):
        s = planner.SCRIPT_SURFACE
        for field in ("block", "type", "item"):
            self.assertIn(field, s, f"the {field} identity field is gone")
        self.assertIn("items[0].item", s, "the inventory read hint is gone")
        self.assertIn("items[0].count", s)
        self.assertIn("undefined", s, "the undefined-not-error warning is gone")
        self.assertIn("a mob entry has `{type, name, position, distance}`", s,
                      "the mob shape is gone")

    def test_no_shape_substitutes_id_for_its_own_identity_field(self):
        """KILLS: replacing any one identity field with `id`, which is the
        exact producer-shape mistake task 4.5 exists to prevent. Presence
        tests alone stay green when `type` becomes `id`, so each shape line is
        pinned separately."""
        s = planner.SCRIPT_SURFACE
        self.assertIn("a block entry has `{id, block, position}`", s)
        self.assertIn("a mob entry has `{type, name, position, distance}`", s)
        self.assertIn("an inventory item has `{slot, item, count, "
                      "display_name, max_stack_size}`", s)
        # The two lines that must NOT say `id` say so explicitly.
        self.assertEqual(2, s.count("NOT `id`"),
                         "expected two 'NOT id' warnings (mob, item)")

    def test_the_wrong_id_read_is_called_out(self):
        """KILLS: dropping the explicit "do not use .id" warning while keeping
        the field list. The warning is what a model actually needs."""
        s = planner.SCRIPT_SURFACE
        self.assertIn("NOT `id`", s, "the 'not id' warning is gone")
        self.assertIn("items[0].id", s, "the concrete wrong-read example is gone")


if __name__ == "__main__":
    unittest.main()

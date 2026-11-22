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


def _prompt_required_fields():
    """{(kind): [field, ...]} as the PROMPT states them, parsed from its text.

    Parsed from the rendered surface rather than read off `_REQUIRED_FIELDS`, so
    a renderer that drops or mangles an entry is caught by comparing against
    the binding, not by comparing the binding with itself.

    Only the `target`-style lines: a field is rendered in double quotes and the
    line ends in a full stop. Coordinate lines render bare and end in "as
    numbers." -- those go through `_prompt_required_coords`, so the two tables
    stay distinguishable in the text they produce.
    """
    out = {}
    for line in planner.SCRIPT_SURFACE.splitlines():
        m = re.match(r'\s*- `"([A-Z][A-Z_]*)"` needs (.+?)\.$', line)
        if not m or m.group(2).endswith("as numbers"):
            continue
        out[m.group(1)] = re.findall(r'`"([a-z_]+)"`', m.group(2))
    return out


def _prompt_required_coords():
    """{(kind): [coord, ...]} as the PROMPT states the coordinate rule."""
    out = {}
    for line in planner.SCRIPT_SURFACE.splitlines():
        m = re.match(r'\s*- `"([A-Z][A-Z_]*)"` needs (.+), as numbers\.$', line)
        if not m:
            continue
        out[m.group(1)] = re.findall(r'`([xyz])`', m.group(2))
    return out


class RequiredFieldsInPromptTest(unittest.TestCase):
    """The prompt must say which arguments a kind cannot do without.

    The wedge on 2026-11-22: a script sent `MINE` with coordinates and no
    `target`; the binding admitted it and the bot's tick loop died. The author
    could not know because the prompt never said. These tests pin the prompt to
    the binding in both directions.
    """

    def test_every_required_kind_and_field_is_named(self):
        from action_binding import _REQUIRED_FIELDS
        self.assertTrue(_REQUIRED_FIELDS, "the required table is empty -- this "
                                          "test would pass vacuously")
        shown = _prompt_required_fields()
        self.assertEqual({k: list(v) for k, v in _REQUIRED_FIELDS.items()}, shown)

    def test_the_prompt_does_not_invent_a_requirement(self):
        """A kind listed as needing an argument, which the binding lets through
        bare, is a false refusal the model will work around."""
        from action_binding import _REQUIRED_FIELDS
        for kind, fields in _prompt_required_fields().items():
            with self.subTest(kind=kind):
                self.assertEqual(list(_REQUIRED_FIELDS.get(kind, ())), fields)
                # And it really is refused without them: the prompt's sentence
                # "an action without one is not dispatched" must be true.
                with self.assertRaises(RefusedAction):
                    bind_action({"kind": kind})

    def test_the_coordinate_rule_matches_the_binding(self):
        """The prompt's coordinate lines must name exactly the kinds the
        binding refuses without coordinates, in both directions: a kind listed
        that binds without them is false advice, and one the binding refuses
        but the prompt omits is the 0,0,0 walk with no warning."""
        from action_binding import _REQUIRED_COORDS
        self.assertTrue(_REQUIRED_COORDS, "the coordinate table is empty -- "
                                          "this test would pass vacuously")
        shown = _prompt_required_coords()
        self.assertEqual({k: list(v) for k, v in _REQUIRED_COORDS.items()}, shown)

    def test_the_coordinate_rule_does_not_catch_build(self):
        """BUILD reads all-zero as "build here", so listing it would tell a
        planner to send coordinates the mod does not need."""
        self.assertNotIn("BUILD", _prompt_required_coords())

    def test_the_coordinates_mistake_is_named(self):
        """The script that wedged the bot looked plausible, so the sentence that
        would have stopped it has to be there."""
        s = planner.SCRIPT_SURFACE
        self.assertIn("never a position", s)
        self.assertIn("do not stand in for it", s)

    def test_nothing_required_leaves_no_stray_slot_or_line(self):
        """If the required table empties, the partial must disappear -- not
        print a bullet saying "none", which is advice the binding never made."""
        raw = '  a plain object.\n' + planner._REQUIRED_FIELDS_SLOT + '\n  Returns x.'
        out = planner._fill_required_fields(raw, {})
        self.assertNotIn("@", out)
        self.assertNotIn("NEED", out)
        self.assertEqual('  a plain object.\n  Returns x.', out)

    def test_a_required_kind_reaches_the_prompt_by_editing_the_binding_only(self):
        """KILLS: the table typed into the prompt. A kind added to the binding's
        required table must appear in a freshly imported prompt, with no prompt
        edit -- the same drift guard the kind list has.

        The kind is STORE_ALL, not GOTO: GOTO now carries a coordinate
        requirement, so it is already in the prompt and could not show a change.
        STORE_ALL is bindable, reads coordinates only under a guard, and is in
        neither required table -- so adding it to _REQUIRED_FIELDS is a real
        edit that must show up.
        """
        import subprocess, sys, os
        here = os.path.dirname(os.path.abspath(__file__))
        probe = (
            "import action_binding, sys\n"
            "assert '`\"STORE_ALL\"` needs' not in __import__('planner').SCRIPT_SURFACE\n"
            "sys.modules.pop('planner', None)\n"
            "action_binding._REQUIRED_FIELDS = dict(action_binding._REQUIRED_FIELDS)\n"
            "action_binding._REQUIRED_FIELDS['STORE_ALL'] = ('target',)\n"
            "import planner\n"
            "assert '`\"STORE_ALL\"` needs `\"target\"`.' in planner.SCRIPT_SURFACE, "
            "'STORE_ALL missing from the prompt after a binding-only edit'\n"
            "print('REQ-OK')\n"
        )
        out = subprocess.run([sys.executable, "-B", "-c", probe], cwd=here,
                             capture_output=True, text=True)
        self.assertEqual(0, out.returncode,
                         f"stdout={out.stdout!r} stderr={out.stderr[-800:]!r}")
        self.assertIn("REQ-OK", out.stdout)


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
        """The end-to-end claim: what the prompt says, the binding accepts.

        A kind the prompt says needs an argument is now bound WITH it -- the
        prompt states the rule, so following the prompt is the thing being
        tested, not a bare `{"kind": ...}` the prompt never promised works."""
        required = _prompt_required_fields()
        coords = _prompt_required_coords()
        for kind in sorted(_example_kinds()):
            with self.subTest(kind=kind):
                action = {"kind": kind}
                for field in required.get(kind, ()):
                    action[field] = "minecraft:stone"
                for field in coords.get(kind, ()):
                    action[field] = 0
                bound = bind_action(action)
                self.assertEqual(kind, bound["kind"])

    def test_lowercase_is_accepted_because_the_prompt_says_so(self):
        """The prompt now tells the model case does not matter; that promise
        must hold or the sentence is a new way to be refused."""
        # MINE needs a target, which says nothing about case; supply it so this
        # stays a test of normalisation and not of the required-field rule.
        self.assertEqual("MINE",
                         bind_action({"kind": "mine", "target": "stone"})["kind"])

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

    def test_removing_a_coordinate_kind_removes_its_prompt_line(self):
        """KILLS: rendering the coordinate table without joining it against
        BINDABLE_KINDS. That join filters nothing while every coordinate kind is
        bindable, so without this probe the filter could be deleted silently and
        the prompt would keep advising coordinates for an action nothing
        accepts. Same separate-process shape as the kind-list drift guard."""
        import subprocess
        import sys
        import os

        here = os.path.dirname(os.path.abspath(__file__))
        probe = (
            "import action_binding, sys, planner\n"
            "assert '`\"GOTO\"` needs `x`' in planner.SCRIPT_SURFACE, 'not there before'\n"
            "sys.modules.pop('planner', None)\n"
            "action_binding.BINDABLE_KINDS = frozenset("
            "action_binding.BINDABLE_KINDS - {'GOTO'})\n"
            "import planner\n"
            "assert '`\"GOTO\"` needs `x`' not in planner.SCRIPT_SURFACE, "
            "'GOTO gone from the binding but its coordinate line is still in the prompt'\n"
            "print('COORD-DRIFT-OK')\n"
        )
        out = subprocess.run([sys.executable, "-B", "-c", probe], cwd=here,
                             capture_output=True, text=True)
        self.assertEqual(0, out.returncode,
                         f"stdout={out.stdout!r} stderr={out.stderr[-800:]!r}")
        self.assertIn("COORD-DRIFT-OK", out.stdout)

    def test_the_examples_are_not_hand_written(self):
        """KILLS: an Examples line typed out, which is how "MINE" survived a
        binding that no longer had it. Every example must be a real kind."""
        m = re.search(r"Examples: (.*?)\. Matching", planner.SCRIPT_SURFACE)
        self.assertIsNotNone(m, "the Examples line is gone or reworded")
        examples = set(re.findall(r'`"([A-Z][A-Z_]*)"`', m.group(1)))
        self.assertEqual(4, len(examples), f"expected 4 examples, got {examples}")
        self.assertEqual(set(), examples - BINDABLE_KINDS,
                         "an example names a kind the binding refuses")


class CoordinateRuleMatchesSourceTest(unittest.TestCase):
    """`_REQUIRED_COORDS` is pinned to the Java behaviour sources, not to itself.

    The rule's premise is that a kind reading `directive.getX()` without an
    `hasLocation()` guard will act at 0,0,0 when sent none. That is a fact
    about the mod, so the test re-derives the set of such kinds from the
    sources rather than comparing the table with the table: a new behaviour
    that reads coordinates unguarded, or an existing one that drops its guard,
    reds here instead of silently walking a bot to origin.
    """

    # Behaviour that reads an all-zero location as "no location given, use a
    # fallback" -- a missing coordinate is valid there, so it is excluded by
    # design. Each entry needs its reason, so excluding one is a claim checked
    # by a human rather than a silent omission.
    _ZERO_MEANS_FALLBACK = {
        "BuildBehavior": "treats all-zero as 'build here' (BuildBehavior.java:99-107)",
    }

    def _behavior_dir(self):
        import os
        here = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(here, "..", "src", "main", "java", "com",
                            "sigmastrain", "aiplayermod", "brain", "behavior")

    # Behaviour class -> DirectiveType it is created for (BehaviorFactory).
    # Read from the factory rather than hard-coded, so a renamed kind is caught.
    def _kind_for_behavior(self):
        import os
        import re
        d = self._behavior_dir()
        factory = os.path.join(d, "BehaviorFactory.java")
        with open(factory, encoding="utf-8") as fh:
            text = fh.read()
        out = {}
        for m in re.finditer(r"case\s+([A-Z_]+)\s*->\s*new\s+(\w+Behavior)",
                             text):
            out[m.group(2)] = m.group(1)
        return out

    def _unguarded_coordinate_readers(self):
        """{BehaviourClass} where a directive coordinate is read with no
        `hasLocation()` guard governing it.

        Structural, not line-based: a guard is either (a) the read is inside an
        `if (directive.hasLocation())` block, or (b) the read is on a line whose
        own expression contains `hasLocation()` (the ternary form). A line-based
        "is hasLocation on this line" check would miss `if (hasLocation()) {`
        followed by reads on later lines (WideSearch, AreaLoot) -- it flagged
        guarded kinds as unguarded, which is how a pin becomes theatre.
        """
        import os
        import re
        d = self._behavior_dir()
        self.assertTrue(os.path.isdir(d), f"behaviour sources not found at {d}")
        found = {}
        for name in sorted(os.listdir(d)):
            if not name.endswith("Behavior.java"):
                continue
            with open(os.path.join(d, name), encoding="utf-8") as fh:
                text = fh.read()
            # Spans a hasLocation() guard governs: everything from an `if
            # (directive.hasLocation()) {` to its matching close brace. Computed
            # by brace matching so a multi-line guard body (WideSearch, AreaLoot)
            # counts, which a per-line check got wrong.
            guarded_spans = []
            for g in re.finditer(r"if\s*\(\s*directive\.hasLocation\(\)\s*\)\s*\{",
                                 text):
                depth = 1
                i = g.end()
                while i < len(text) and depth:
                    if text[i] == "{":
                        depth += 1
                    elif text[i] == "}":
                        depth -= 1
                    i += 1
                guarded_spans.append((g.start(), i))

            def guarded(pos):
                if any(a <= pos < b for a, b in guarded_spans):
                    return True
                # The ternary / one-line form: hasLocation() on the same line.
                line_start = text.rfind("\n", 0, pos) + 1
                line = text[line_start:text.find("\n", pos)]
                return "hasLocation()" in line

            unguarded = [text[text.rfind("\n", 0, m.start()) + 1:
                              text.find("\n", m.start())].strip()
                         for m in re.finditer(r"directive\.get[XYZ]\(\)", text)
                         if not guarded(m.start())]
            if unguarded:
                found[name[:-len(".java")]] = unguarded
        return found

    def test_the_table_matches_every_unguarded_reader(self):
        from action_binding import _REQUIRED_COORDS
        unguarded = self._unguarded_coordinate_readers()
        kinds = self._kind_for_behavior()
        # Map behaviour class -> directive kind through the factory.
        unguarded_kinds = set()
        for cls in unguarded:
            self.assertIn(cls, kinds, f"{cls} has no case in BehaviorFactory; "
                                      "the factory parse or the class name is stale")
            if cls in self._ZERO_MEANS_FALLBACK:
                continue
            unguarded_kinds.add(kinds[cls])
        expected = unguarded_kinds
        self.assertEqual(
            expected, set(_REQUIRED_COORDS),
            "a behaviour reads directive coordinates without an hasLocation() "
            "guard (or one gained/lost a guard) and _REQUIRED_COORDS disagrees. "
            f"unguarded kinds: {sorted(unguarded_kinds)}; "
            f"raw: { {k: v for k, v in unguarded.items()} }. If one of these "
            "treats a zero as a fallback, add it to _ZERO_MEANS_FALLBACK with "
            "its reason; otherwise add it to _REQUIRED_COORDS.")


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

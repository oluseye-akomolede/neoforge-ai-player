"""Tests for agent/action_binding.py — M2 task 3.2.

Two things must hold, and the second is the one that gets skipped:

1. An unknown action is refused and executes nothing.
2. The bindable set is the agent's REAL dispatch set -- not a set that happens
   to be written down twice. `bindable_set_matches_source` parses the live
   agent.py and l3_planner.py so the copy in action_binding.py cannot drift.

Loaded by path (no `agent` package import) so it runs without psycopg2/uvicorn.
"""

import ast
import importlib.util
import json
import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ab = _load("action_binding_under_test", "action_binding.py")

AGENT_SIDE_KINDS = _ab.AGENT_SIDE_KINDS
BINDABLE_KINDS = _ab.BINDABLE_KINDS
MOD_DIRECTIVE_KINDS = _ab.MOD_DIRECTIVE_KINDS
RefusedAction = _ab.RefusedAction
bind_action = _ab.bind_action
bind_actions = _ab.bind_actions
_REQUIRED_FIELDS = _ab._REQUIRED_FIELDS
_REQUIRED_COORDS = _ab._REQUIRED_COORDS
to_directive = _ab.to_directive


class BindableSetMatchesSourceTest(unittest.TestCase):
    """The anti-drift guard. A copied vocabulary is only safe while pinned."""

    def test_mod_kinds_match_the_planner(self):
        # Read _VALID_DIRECTIVE_KINDS out of l3_planner.py without importing it
        # (it pulls in the planner's deps).
        with open(os.path.join(_HERE, "l3_planner.py"), encoding="utf-8") as f:
            planner_src = f.read()
        tree = ast.parse(planner_src)
        found = None
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    if isinstance(t, ast.Name) and t.id == "_VALID_DIRECTIVE_KINDS":
                        found = {e.value for e in node.value.args[0].elts}
        self.assertIsNotNone(found, "could not find _VALID_DIRECTIVE_KINDS in l3_planner.py")
        self.assertEqual(MOD_DIRECTIVE_KINDS, frozenset(found),
                         "action_binding.MOD_DIRECTIVE_KINDS has drifted from the planner")

    def test_agent_side_kinds_match_the_dispatch(self):
        # Scan Agent._dispatch's `if kind ==` / `if kind in (...)` comparisons.
        with open(os.path.join(_HERE, "agent.py"), encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
        handled = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            t = node.test
            if not (isinstance(t, ast.Compare) and isinstance(t.left, ast.Name)
                    and t.left.id == "kind"):
                continue
            for comp in t.comparators:
                if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                    handled.add(comp.value)
                elif isinstance(comp, ast.Tuple):
                    for e in comp.elts:
                        if isinstance(e, ast.Constant) and isinstance(e.value, str):
                            handled.add(e.value)
        self.assertTrue(handled, "found no `kind` comparisons in agent.py - bad query")
        self.assertTrue(AGENT_SIDE_KINDS <= handled,
                        f"claimed agent-side but never dispatched: "
                        f"{sorted(AGENT_SIDE_KINDS - handled)}")


class RefusalTest(unittest.TestCase):

    def test_unknown_action_is_refused_by_name(self):
        with self.assertRaises(RefusedAction) as ctx:
            bind_action({"kind": "WORLD_EDIT"})
        self.assertIn("WORLD_EDIT", str(ctx.exception))

    def test_refusal_happens_before_any_dispatch(self):
        # The load-bearing property of 3.2: nothing executes. Bind the whole
        # list and prove the refused one produced no directive at all, rather
        # than a directive some later layer was expected to drop.
        bound, refusals = bind_actions([
            {"kind": "MINE", "target": "iron_ore"},
            {"kind": "WORLD_EDIT", "target": "everything"},
        ])
        self.assertEqual(len(bound), 1)
        self.assertEqual(bound[0]["kind"], "MINE")
        self.assertEqual(len(refusals), 1)
        self.assertEqual(refusals[0]["index"], 1)
        self.assertEqual(refusals[0]["kind"], "WORLD_EDIT")

    def test_type_smuggling_is_refused(self):
        # A script setting `type` directly would reach a handler name the
        # binding never approved.
        with self.assertRaises(RefusedAction) as ctx:
            bind_action({"kind": "MINE", "type": "OP_ALL"})
        self.assertIn("type", str(ctx.exception))

    def test_unsupported_argument_is_refused_not_dropped(self):
        with self.assertRaises(RefusedAction) as ctx:
            bind_action({"kind": "MINE", "target": "iron_ore", "player": "Scout"})
        self.assertIn("player", str(ctx.exception))

    def test_missing_kind_is_refused(self):
        for bad in ({}, {"target": "x"}, {"kind": ""}, {"kind": None}):
            with self.assertRaises(RefusedAction):
                bind_action(bad)

    def test_non_dict_action_is_refused(self):
        for bad in ("MINE", ["MINE"], None, 42):
            with self.assertRaises(RefusedAction):
                bind_action(bad)

    def test_empty_action_list_is_normal_not_a_failure(self):
        # The silence case depends on "no actions" being a clean result.
        bound, refusals = bind_actions([])
        self.assertEqual((bound, refusals), ([], []))


class BindingTest(unittest.TestCase):

    def test_kind_is_uppercased_and_arguments_keep_their_values(self):
        b = bind_action({"kind": "store_all", "x": 1, "y": 64, "z": -3})
        self.assertEqual(b, {"kind": "STORE_ALL", "x": 1, "y": 64, "z": -3})

    def test_partial_coordinates_are_carried_verbatim(self):
        # The binding does not judge completeness - the mod does
        # (api.py:437 needs all three). Dropping a partial triple here would
        # hide that from the script's author.
        b = bind_action({"kind": "STORE_ALL", "x": 1, "y": 64})
        self.assertEqual(b, {"kind": "STORE_ALL", "x": 1, "y": 64})

    def test_agent_side_verbs_bind(self):
        for kind in ("EQUIP_ALL", "DROP", "STORE", "ASK_PLAYER"):
            self.assertEqual(bind_action({"kind": kind})["kind"], kind)

    def test_to_directive_renames_kind_to_type(self):
        d = to_directive(bind_action({"kind": "MINE", "target": "iron_ore"}))
        self.assertEqual(d, {"type": "MINE", "target": "iron_ore"})

    def test_to_directive_refuses_a_smuggled_type(self):
        with self.assertRaises(RefusedAction):
            to_directive({"kind": "MINE", "type": "OP_ALL"})

    def test_every_bindable_kind_actually_binds(self):
        # The set and the function agree for all members, so a kind added to
        # the set but rejected by the code (or vice versa) is visible here.
        # A kind that requires a field gets one, so this still proves the set
        # and the checker agree rather than re-testing the required-field rule.
        for kind in sorted(BINDABLE_KINDS):
            action = {"kind": kind}
            for field in _REQUIRED_FIELDS.get(kind, ()):
                action[field] = "minecraft:stone"
            for field in _REQUIRED_COORDS.get(kind, ()):
                action[field] = 0
            self.assertEqual(bind_action(action)["kind"], kind)


class RequiredFieldTest(unittest.TestCase):
    """A directive missing a field its kind needs is refused, never dispatched.

    The failure this prevents, from the live trial on 2026-11-22: a script sent
    `MINE {x, y, z}` with no target, the allow-list admitted it, the mod
    installed MineBehavior, and start() NPE'd on a null target before
    enterPhase() -- so every server tick re-threw it and the bot stopped
    answering for eight minutes.
    """

    def test_mine_without_a_target_is_refused(self):
        with self.assertRaises(RefusedAction) as ctx:
            bind_action({"kind": "MINE", "x": 16, "y": 89, "z": -16})
        self.assertIn("target", str(ctx.exception))

    def test_every_required_field_kind_refuses_a_missing_one(self):
        # Parametrised over the table, not just MINE: a row with no test
        # survives an edit that special-cases its kind, and the other three
        # kinds in _REQUIRED_FIELDS would then be unchecked.
        self.assertTrue(_REQUIRED_FIELDS, "empty table proves nothing")
        for kind, fields in sorted(_REQUIRED_FIELDS.items()):
            for field in fields:
                with self.assertRaises(RefusedAction,
                                       msg=f"{kind} without {field}") as ctx:
                    bind_action({"kind": kind})
                self.assertIn(field, str(ctx.exception),
                              f"{kind} refusal must name {field}")

    def test_every_required_field_kind_refuses_a_blank_one(self):
        # Same rule as MINE's blank case, applied to every row: blank is the
        # absent value that survives a presence check.
        for kind, fields in sorted(_REQUIRED_FIELDS.items()):
            for field in fields:
                with self.assertRaises(RefusedAction,
                                       msg=f"{kind} with blank {field}"):
                    bind_action({"kind": kind, field: "   "})

    def test_every_required_field_kind_binds_when_supplied(self):
        # The refusal must be about the missing field, not the kind: supplying
        # every required field (and any coordinates) binds.
        for kind, fields in sorted(_REQUIRED_FIELDS.items()):
            action = {"kind": kind}
            for field in fields:
                action[field] = "minecraft:stone"
            for field in _REQUIRED_COORDS.get(kind, ()):
                action[field] = 1
            self.assertEqual(bind_action(action)["kind"], kind,
                             f"{kind} with its required fields should bind")

    def test_the_refusal_names_coordinates_as_the_likely_mistake(self):
        # The script that wedged the bot looked plausible. Saying only "missing
        # target" leaves its author to repeat the guess, so the reason has to
        # say that a block id goes in target and x/y/z are not coordinates.
        with self.assertRaises(RefusedAction) as ctx:
            bind_action({"kind": "MINE", "x": 16})
        self.assertIn("not coordinates", str(ctx.exception))

    def test_a_blank_target_is_missing_not_present(self):
        # "  " passes a presence check and reaches the same NPE as absent.
        for blank in ("", "   ", "\t"):
            with self.assertRaises(RefusedAction, msg=f"target={blank!r}"):
                bind_action({"kind": "MINE", "target": blank})

    def test_a_real_target_binds_and_keeps_its_fields(self):
        bound = bind_action({"kind": "MINE", "target": "minecraft:dirt", "count": 4})
        self.assertEqual(bound["kind"], "MINE")
        self.assertEqual(bound["target"], "minecraft:dirt")
        self.assertEqual(bound["count"], 4)

    def test_goto_takes_coordinates_not_a_target(self):
        # The reverse guard: GOTO genuinely reads x/y/z (GotoBehavior.java:36-38),
        # so a required-target table applied to it would refuse every valid goto.
        bound = bind_action({"kind": "GOTO", "x": 10, "y": 70, "z": -5})
        self.assertEqual(bound["kind"], "GOTO")

    def test_every_kind_in_the_required_table_is_bindable(self):
        # A table naming a kind that is not in the dispatch set is dead, and a
        # rule nobody can reach is a rule nobody has tested.
        for kind in _REQUIRED_FIELDS:
            self.assertIn(kind, BINDABLE_KINDS,
                          f"_REQUIRED_FIELDS names {kind}, which cannot be dispatched")


class RequiredCoordsTest(unittest.TestCase):
    """A kind whose coordinates are always meaningful is refused without them.

    From the 21b2ec4 review: `Directive`'s x/y/z are primitive doubles
    defaulting to 0.0 and hasLocation is set only by location(...). GOTO and
    TELEPORT read getX/getY/getZ unconditionally in start(), so a targetless
    GOTO bound and the bot walked to 0,0,0 -- an action never asked for.
    """

    def test_goto_without_coordinates_is_refused(self):
        # The reason names the first gap and says what the action would have
        # done. It is not asserted to list all three: the "0,0,0" in the hint
        # would match 'y'/'z' by accident, so a "names every field" check here
        # would pass even if only one were ever named.
        with self.assertRaises(RefusedAction) as ctx:
            bind_action({"kind": "GOTO"})
        self.assertIn("coordinate 'x'", str(ctx.exception))
        self.assertIn("0,0,0", str(ctx.exception))

    def test_teleport_without_coordinates_is_refused(self):
        with self.assertRaises(RefusedAction) as ctx:
            bind_action({"kind": "TELEPORT",
                         "extra": {"dimension": "minecraft:the_nether"}})
        self.assertIn("coordinate 'x'", str(ctx.exception))

    def test_teleport_with_a_partial_triple_is_refused_and_names_the_gap(self):
        # y given, x and z not: the reason must name the first absent one
        # rather than repeat a generic "needs coordinates".
        with self.assertRaises(RefusedAction) as ctx:
            bind_action({"kind": "GOTO", "y": 64})
        self.assertIn("'x'", str(ctx.exception))

    def test_zero_is_a_coordinate_not_an_absence(self):
        # The bug this guards: treating 0 like "unset" would refuse a real
        # destination on an axis, so a bot could never be sent to x=0.
        bound = bind_action({"kind": "GOTO", "x": 0, "y": 64, "z": 0})
        self.assertEqual(bound, {"kind": "GOTO", "x": 0, "y": 64, "z": 0})

    def test_a_string_coordinate_is_refused_not_coerced(self):
        # The mod takes a double; "16" there is a script bug worth surfacing,
        # not something to guess at.
        for bad in ("16", True, None):
            with self.assertRaises(RefusedAction, msg=repr(bad)):
                bind_action({"kind": "GOTO", "x": bad, "y": 64, "z": 0})

    def test_a_non_finite_coordinate_is_refused(self):
        # From the 7e72410 review. isinstance() calls all three of these
        # numbers, so a type check alone binds them.
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(RefusedAction, msg=repr(bad)):
                bind_action({"kind": "GOTO", "x": bad, "y": 64, "z": 0})

    def test_a_nan_from_a_model_reply_is_refused_at_ingress(self):
        # Reachability, testable without a model: json.loads accepts the bare
        # tokens NaN/Infinity, which is how a reply reaches bind_action. If
        # this ever stops raising, the ingress parser gained a guard and the
        # binding check became belt-and-braces rather than the only control.
        parsed = json.loads('{"kind": "GOTO", "x": NaN, "y": 64, "z": 0}')
        with self.assertRaises(RefusedAction):
            bind_action(parsed)

    def test_the_refusal_shows_the_bad_value_not_just_the_keys(self):
        # A NaN WAS sent. "it was not sent" would be a false statement that
        # sends the script's author looking for a missing key.
        with self.assertRaises(RefusedAction) as ctx:
            bind_action({"kind": "GOTO", "x": float("nan"), "y": 64, "z": 0})
        self.assertIn("nan", str(ctx.exception))
        self.assertIn("finite", str(ctx.exception))
        self.assertNotIn("was not sent", str(ctx.exception))

    def test_build_is_not_in_the_coordinate_table(self):
        # BuildBehavior treats all-zero as "build here", so requiring coords
        # would refuse a working call. The table must not grow to include it.
        self.assertNotIn("BUILD", _REQUIRED_COORDS)
        self.assertEqual(bind_action({"kind": "BUILD", "target": "shelter"})["kind"],
                         "BUILD")

    def test_every_coordinate_kind_is_bindable(self):
        self.assertTrue(_REQUIRED_COORDS, "empty table proves nothing")
        for kind in _REQUIRED_COORDS:
            self.assertIn(kind, BINDABLE_KINDS,
                          f"_REQUIRED_COORDS names {kind}, which cannot be dispatched")


if __name__ == "__main__":
    unittest.main(verbosity=2)

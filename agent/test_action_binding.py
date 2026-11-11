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
        for kind in sorted(BINDABLE_KINDS):
            self.assertEqual(bind_action({"kind": kind})["kind"], kind)


if __name__ == "__main__":
    unittest.main(verbosity=2)

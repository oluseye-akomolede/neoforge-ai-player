"""Directive names arriving from a script: case, and unknown names.

Stdlib only: `python3 agent/tests/test_directive_names.py` from the repo root.

Two facts about the mod drive this file, both read from source, not assumed:

  1. HttpApiServer.java:1341 does `body.get("type").getAsString().toUpperCase()`
     before `DirectiveType.valueOf(...)`. So the mod ALREADY accepts "mine".
     An earlier draft of M2-PLAN reasoned that lowercase "would reach the mod
     and fail there" -- that is false on this mod revision, and a test that
     expected a rejection would have encoded the wrong behaviour.

  2. `DirectiveType.valueOf` throws IllegalArgumentException for a name it does
     not know. That throw happens inside the request handler, so the agent sees
     an HTTP 500 with no name in it -- the error is far from the cause.

So the agent normalises case (matching the mod, so both spell it the same way)
and rejects an unknown name where the payload is still visible, naming it.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import script_client  # noqa: E402  (needs the path above)


class NormaliseDirectiveNameTest(unittest.TestCase):
    """Case is normalised, because the mod normalises it too."""

    def test_lowercase_is_upper_cased(self):
        self.assertEqual(script_client.normalise_directive_name("mine"), "MINE")

    def test_mixed_case_is_upper_cased(self):
        self.assertEqual(script_client.normalise_directive_name("GoTo"), "GOTO")

    def test_already_upper_is_unchanged(self):
        self.assertEqual(script_client.normalise_directive_name("SEND_ITEM"), "SEND_ITEM")

    def test_surrounding_whitespace_is_stripped(self):
        # A trailing newline in a script literal is a plausible typo and costs
        # nothing to absorb; it is not a different directive name.
        self.assertEqual(script_client.normalise_directive_name("  mine\n"), "MINE")


class RejectUnknownDirectiveNameTest(unittest.TestCase):
    """An unknown name is refused here, where it can be named."""

    def test_unknown_name_raises_with_the_name_in_the_message(self):
        with self.assertRaises(script_client.UnknownDirective) as ctx:
            script_client.normalise_directive_name("NOT_A_REAL_DIRECTIVE")
        self.assertIn("NOT_A_REAL_DIRECTIVE", str(ctx.exception))

    def test_unknown_name_is_not_silently_passed_through(self):
        # The defect being prevented: a wrong name reaching the mod and throwing
        # there. Assert the refusal is an exception the caller must handle.
        try:
            script_client.normalise_directive_name("not_a_real_directive")
        except script_client.UnknownDirective:
            return
        self.fail("unknown directive name was not refused")

    def test_empty_name_is_refused(self):
        with self.assertRaises(script_client.UnknownDirective):
            script_client.normalise_directive_name("")

    def test_non_string_is_refused(self):
        # A script can call api.do(123) or api.do(None). Neither is a directive.
        for bad in (None, 123, ["MINE"], {"kind": "MINE"}):
            with self.subTest(bad=bad):
                with self.assertRaises(script_client.UnknownDirective):
                    script_client.normalise_directive_name(bad)


class KindSetTest(unittest.TestCase):
    """The accepted set is the mod's DirectiveType, not a hand-copied list."""

    def test_known_kinds_are_accepted(self):
        for name in ("MINE", "GOTO", "SEND_ITEM", "UNFUSE_BLOCK"):
            with self.subTest(name=name):
                self.assertEqual(
                    script_client.normalise_directive_name(name.lower()), name)

    def test_agent_side_aliases_are_not_mod_directives(self):
        # EQUIP_ALL is real vocabulary in agent.py:905-908, where it maps to the
        # mod's synchronous equip_all action -- but it is NOT a DirectiveType,
        # so posting it as {"type": "EQUIP_ALL"} would throw at the mod. It must
        # be refused here rather than carried into the directive set. This
        # assertion is the distinction the plan draws at :280-282 between a
        # valid name and a callable one.
        with self.assertRaises(script_client.UnknownDirective):
            script_client.normalise_directive_name("EQUIP_ALL")

    def test_the_set_does_not_contain_near_misses(self):
        # Guards against a typo being "close enough"; the mod is exact after
        # upper-casing, so this set must be exact too.
        for name in ("MINING", "GOTO_", "SENDITEMS"):
            with self.subTest(name=name):
                with self.assertRaises(script_client.UnknownDirective):
                    script_client.normalise_directive_name(name)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Per-bot L3 routing: which bots reach the path the script surface lives on.

Written against "The Script Surface Needs The L3 Path, And SCRIPT_BOTS Opts A
Bot Into It". Before this, all three routing sites asked the deployment-wide
``USE_L3_PLAN_LAYER`` and nothing else, so prod -- which does not set the flag
-- planned every chat through ``decompose`` and no prod bot could ever reach
the L3 plan prompt where the script surface is spliced. Enabling it there would
have moved all five bots at once.

Two properties are easy to lose and are pinned separately here:

* The flag keeps working exactly as before. A bot not named in ``SCRIPT_BOTS``
  must not change routing because this feature shipped.
* Reachability is not offering. A bot named for scripts still gets no script
  section without a runner; that belongs to ``script_mode`` and is asserted
  against it rather than reimplemented.
"""

import unittest
from unittest import mock

# Reused, not copied: importing this sibling installs the stub modules
# agent.py needs at module scope (psycopg2, fastapi, ...). The same seam
# test_l3_script_path.py uses, so the stub list stays in one place.
import test_agent_script_branch  # noqa: F401
import planner


class L3PathPredicateTest(unittest.TestCase):
    """`planner.l3_path_enabled` -- the one predicate behind all three sites."""

    def test_flag_on_routes_every_bot_unchanged(self):
        # The pre-existing behaviour. A deployment that sets the flag today
        # must see no change at all, for a named bot and an unnamed one alike.
        for bot in ("Forge", "Scout"):
            on, _why = planner.l3_path_enabled(
                bot, use_l3_plan_layer=True, enabled_bots="Forge")
            self.assertTrue(on, f"{bot} must keep the L3 path when the flag is on")

    def test_flag_off_and_named_takes_the_l3_path(self):
        # The whole point of the change: prod's case, flag unset.
        on, why = planner.l3_path_enabled(
            "Forge", use_l3_plan_layer=False, enabled_bots="Forge")
        self.assertTrue(on)
        self.assertIn("SCRIPT_BOTS", why)

    def test_flag_off_and_unnamed_stays_on_decompose(self):
        on, _why = planner.l3_path_enabled(
            "Scout", use_l3_plan_layer=False, enabled_bots="Forge")
        self.assertFalse(on)

    def test_flag_off_and_unset_bots_routes_nobody(self):
        # An unset SCRIPT_BOTS must not become "everybody": that is how prod
        # would silently move onto a path it never opted into.
        for bot in ("Forge", "Scout"):
            self.assertFalse(
                planner.l3_path_enabled(bot, use_l3_plan_layer=False,
                                        enabled_bots="")[0])

    def test_match_is_case_insensitive_and_trims(self):
        for bot, names in (("forge", " Forge "), (" FORGE ", "Forge"),
                           ("Mystic", "forge, MYSTIC ")):
            self.assertTrue(
                planner.l3_path_enabled(bot, use_l3_plan_layer=False,
                                        enabled_bots=names)[0],
                f"{bot!r} must match {names!r}")

    def test_reason_names_which_way_it_was_enabled(self):
        # Two ways in, so "on" is not the useful diagnostic. A deployment
        # reading its logs needs to know whether it opted the fleet in or one
        # bot, because the two have different blast radius.
        _on, by_flag = planner.l3_path_enabled(
            "Forge", use_l3_plan_layer=True, enabled_bots="")
        _on, by_name = planner.l3_path_enabled(
            "Forge", use_l3_plan_layer=False, enabled_bots="Forge")
        self.assertIn("USE_L3_PLAN_LAYER", by_flag)
        self.assertIn("SCRIPT_BOTS", by_name)
        self.assertNotEqual(by_flag, by_name)

    def test_reads_environment_when_arguments_are_omitted(self):
        # The production call path omits enabled_bots and relies on the env.
        with mock.patch.dict("os.environ",
                             {"SCRIPT_BOTS": "Forge"}, clear=False):
            import os
            os.environ.pop("USE_L3_PLAN_LAYER", None)
            self.assertTrue(planner.l3_path_enabled("Forge")[0])
            self.assertFalse(planner.l3_path_enabled("Scout")[0])

    def test_flag_is_read_from_environment_when_omitted(self):
        with mock.patch.dict("os.environ",
                             {"USE_L3_PLAN_LAYER": "true", "SCRIPT_BOTS": ""},
                             clear=False):
            self.assertTrue(planner.l3_path_enabled("Scout")[0])


class ReachabilityIsNotOfferingTest(unittest.TestCase):
    """Listing a bot buys it the path, never the prompt section."""

    def test_named_bot_without_runner_reaches_l3_but_is_offered_nothing(self):
        # Both halves in one place, because either alone is a wrong product:
        # routing it without a runner is correct (the path is where a script
        # WOULD run), and offering it a section with no runner is not.
        on, _ = planner.l3_path_enabled(
            "Forge", use_l3_plan_layer=False, enabled_bots="Forge")
        offered, why = planner.script_mode("Forge", "Forge", "")
        self.assertTrue(on, "naming a bot must route it to L3")
        self.assertFalse(offered, "no runner means no script section")
        self.assertIn("SCRIPT_RUNNER_URL", why)

    def test_named_bot_with_runner_is_both(self):
        on, _ = planner.l3_path_enabled(
            "Forge", use_l3_plan_layer=False, enabled_bots="Forge")
        offered, _ = planner.script_mode("Forge", "Forge", "http://runner")
        self.assertTrue(on)
        self.assertTrue(offered)


class AgentHelperIsRobustToAFakedModuleTest(unittest.TestCase):
    """`agent._l3_path_enabled` must not unpack a Mock.

    Several existing tests patch the whole `planner` module to fake
    `decompose`, which makes the predicate return a Mock. An `on, _ = ...`
    would turn that fixture into a ValueError inside production code -- which
    is exactly what happened before this branch existed. Anything that is not
    a 2-tuple falls back to the flag, i.e. the pre-feature behaviour.
    """

    def _helper(self, answer, flag):
        import agent as agent_mod
        with mock.patch.dict("os.environ", {}, clear=False):
            with mock.patch.object(agent_mod.planner, "l3_path_enabled",
                                   return_value=answer), \
                    mock.patch.object(agent_mod, "USE_L3_PLAN_LAYER", flag):
                return agent_mod._l3_path_enabled("Forge")

    def test_a_mock_answer_falls_back_to_the_flag_instead_of_raising(self):
        self.assertIs(self._helper(mock.Mock(), True), True)
        self.assertIs(self._helper(mock.Mock(), False), False)

    def test_a_real_tuple_is_honoured(self):
        self.assertIs(self._helper((True, "by SCRIPT_BOTS"), False), True)
        self.assertIs(self._helper((False, "off"), True), False)

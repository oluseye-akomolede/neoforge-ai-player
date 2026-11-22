"""The per-bot script switch: who is offered the script surface, and why.

Written against "The Script Surface Is Offered Per Bot, Not Per Deployment".
Before this, `render_planner_prompt` substituted SCRIPT_SURFACE
unconditionally, so prod (no runner, five bots) would have offered every bot
scripts that could only fail at tick.

Each test names the branch it pins, because the three ways to be OFF are
easily collapsed into one and a deployment reading its startup log needs to
tell them apart.
"""

import json
import os
import unittest
from unittest.mock import patch

import planner


ENV_ON = {"SCRIPT_BOTS": "Forge,Mystic", "SCRIPT_RUNNER_URL": "http://runner"}


class ScriptModeTest(unittest.TestCase):
    def test_enabled_and_runner_is_on(self):
        offered, why = planner.script_mode("Forge", "Forge,Mystic", "http://r")
        self.assertTrue(offered)
        self.assertIn("on", why)

    def test_match_is_case_insensitive_and_trims(self):
        # A deployment writes "Forge" or " forge "; neither should be a silent
        # mismatch against the bot's own name.
        self.assertTrue(planner.script_mode("forge", " Forge , Mystic ", "http://r")[0])
        self.assertTrue(planner.script_mode(" FORGE ", "Forge", "http://r")[0])

    def test_not_named_is_off_and_says_so(self):
        offered, why = planner.script_mode("Scout", "Forge,Mystic", "http://r")
        self.assertFalse(offered)
        self.assertIn("not named", why)
        self.assertIn("Scout", why)

    def test_named_but_no_runner_is_off_and_says_so(self):
        # The half that a name-only gate would miss: a bot listed on a
        # deployment with nowhere to run a script must not be offered one.
        offered, why = planner.script_mode("Forge", "Forge", "")
        self.assertFalse(offered)
        self.assertIn("SCRIPT_RUNNER_URL", why)

    def test_unset_enabled_set_is_off_for_everyone(self):
        # The default is OFF on purpose: "unset means everyone" is how a
        # deployment that never opted in starts offering scripts.
        for enabled in ("", None, " , , "):
            with self.subTest(enabled=enabled):
                offered, why = planner.script_mode("Forge", enabled, "http://r")
                self.assertFalse(offered)
                self.assertIn("names no bot", why)

    def test_no_bot_name_is_off(self):
        # render_planner_prompt defaults bot_name to None; an unidentified
        # caller must not inherit another bot's opt-in.
        self.assertFalse(planner.script_mode(None, "Forge", "http://r")[0])

    def test_reads_the_environment_when_not_passed(self):
        # Production passes nothing, so the env path is the live one.
        with patch.dict(os.environ, ENV_ON):
            self.assertTrue(planner.script_mode("Forge")[0])
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(planner.script_mode("Forge")[0])


class PlannerPromptGateTest(unittest.TestCase):
    def test_enabled_bot_gets_the_surface(self):
        rendered = planner.render_planner_prompt(
            bot_name="Forge", enabled_bots="Forge", runner_url="http://r")
        self.assertIn("api.result", rendered)

    def test_disabled_bot_gets_no_surface(self):
        # Asserted on a marker the surface carries, not on the section header
        # alone: the header could survive while the calls were stripped.
        rendered = planner.render_planner_prompt(
            bot_name="Scout", enabled_bots="Forge", runner_url="http://r")
        self.assertNotIn("api.result", rendered)
        self.assertNotIn(planner.SCRIPT_SURFACE[:200], rendered)

    def test_no_runner_means_no_surface_even_when_named(self):
        rendered = planner.render_planner_prompt(
            bot_name="Forge", enabled_bots="Forge", runner_url="")
        self.assertNotIn("api.result", rendered)


class StrayScriptIgnoredTest(unittest.TestCase):
    def test_a_disabled_bots_script_is_dropped(self):
        parsed = {"script": "const s = api.recall();"}
        with patch("builtins.print") as printed:
            got = planner._script_from(parsed, bot_name="Scout",
                                       enabled_bots="Forge",
                                       runner_url="http://r")
        self.assertIsNone(got, "a bot never offered scripts must not run one")
        printed.assert_called_once()
        self.assertIn("Scout", printed.call_args[0][0])

    def test_an_enabled_bots_script_is_kept(self):
        parsed = {"script": "const s = api.recall();"}
        got = planner._script_from(parsed, bot_name="Forge",
                                   enabled_bots="Forge",
                                   runner_url="http://r")
        self.assertEqual(got, "const s = api.recall();")


class DecomposeThreadsTheBotTest(unittest.TestCase):
    """The switch is only real if `decompose` passes the bot through.

    A gate that defaults to OFF and a caller that never passes a name is
    indistinguishable from "scripts are broken": every legitimate script
    would be silently dropped. That is a worse defect than the one the gate
    fixes, so it gets its own test on the end-to-end path.
    """

    def _run(self, content, env, bot_name):
        class _R:
            def __init__(self, p):
                self._p = p

            def raise_for_status(self):
                return None

            def json(self):
                return self._p

        body = {"message": {"content": content}, "done_reason": "stop"}
        with patch.object(planner.requests, "post", return_value=_R(body)), \
                patch.object(planner, "openai_brain") as fake_l4, \
                patch.dict(os.environ, env, clear=True):
            fake_l4.is_available.return_value = False
            return planner.decompose("m", "chop a tree", bot_name=bot_name)

    def test_an_enabled_bot_keeps_its_script(self):
        r = self._run(json.dumps({"script": "api.noop();"}),
                      {"SCRIPT_BOTS": "Forge",
                       "SCRIPT_RUNNER_URL": "http://r"}, "Forge")
        self.assertEqual(r.script, "api.noop();")

    def test_a_disabled_bot_loses_it(self):
        with patch("builtins.print"):
            r = self._run(json.dumps({"script": "api.noop();"}),
                          {"SCRIPT_BOTS": "Mystic",
                           "SCRIPT_RUNNER_URL": "http://r"}, "Forge")
        self.assertIsNone(r.script)


if __name__ == "__main__":
    unittest.main()

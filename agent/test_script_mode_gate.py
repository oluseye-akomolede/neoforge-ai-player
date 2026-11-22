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
import json as _json
import os
import unittest
from unittest import mock
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


class TestThePlanPromptDoesNotInviteWhatIsNotOffered(unittest.TestCase):
    """Withholding the surface inside a call that still happens does not save
    the call. The L3 plan prompt taught `wants_script` unconditionally and
    call_plan fired the second call on it, so a bot outside SCRIPT_BOTS asked
    for a script it could not have and paid a planner call to find out."""

    _PLAN = {"task": "keep the furnace fed",
             "subtasks": [{"id": 1, "description": "feed", "criteria": "fed"}],
             "wants_script": True}

    def _prompt(self, bot_name, env):
        """Render through production's own renderer, never a copy of it: a test
        that re-implements the gate passes even when production's is removed."""
        import l3_planner
        with patch.dict(os.environ, env, clear=True):
            return l3_planner.render_plan_prompt(bot_name)

    def test_a_disabled_bot_is_not_taught_wants_script(self):
        """KILLS: gating only the surface, so the plan prompt still explains
        the flag and the model asks for what the deployment cannot honour."""
        p = self._prompt("Forge", {"SCRIPT_BOTS": "Mystic",
                                   "SCRIPT_RUNNER_URL": "http://r"})
        self.assertNotIn("wants_script", p)
        self.assertNotIn("Choose between a STEP LIST and a SCRIPT", p)
        self.assertNotIn("api.do(action)", p,
                         "the surface leaked into a disabled bot's plan prompt")

    def test_an_enabled_bot_is_taught_it(self):
        """KILLS: gating the invitation so hard that a bot WITH scripts loses
        the teaching and never scripts a repeating goal."""
        p = self._prompt("Forge", {"SCRIPT_BOTS": "Forge",
                                   "SCRIPT_RUNNER_URL": "http://r"})
        self.assertIn("wants_script", p)
        self.assertIn("Choose between a STEP LIST and a SCRIPT", p)
        self.assertIn("api.do(action)", p)

    def test_a_disabled_bot_that_asks_anyway_costs_no_second_call(self):
        """A prompt is not a contract. KILLS: relying on the prompt alone, so a
        model that sets the flag from habit still pays the script call."""
        import l3_planner
        calls = []

        def _p(content):
            r = mock.Mock()
            r.raise_for_status = mock.Mock()
            r.json = mock.Mock(return_value={"message": {"content": content},
                                             "done_reason": "stop"})
            return r

        def fake_post(url, json=None, timeout=None, **kw):
            calls.append(json)
            return _p(_json.dumps(self._PLAN))

        with patch.object(l3_planner.requests, "post", side_effect=fake_post), \
                patch.object(l3_planner.trajectory_log, "log_call",
                             return_value="c"), \
                patch("builtins.print"), \
                patch.dict(os.environ, {"SCRIPT_BOTS": "Mystic",
                                        "SCRIPT_RUNNER_URL": "http://r"},
                           clear=True):
            plan = l3_planner.call_plan("m", "Forge", "keep the furnace fed")

        self.assertEqual(len(calls), 1, "a second call was made for a bot not offered scripts")
        self.assertIsNone(getattr(plan, "script", None))
        self.assertEqual(len(plan.subtasks), 1,
                         "declining the script must still run the plan's steps")

    def test_an_enabled_bot_that_asks_still_gets_its_script(self):
        """KILLS: refusing the fetch unconditionally -- the gate must decide
        per bot, so threading bot_name wrongly cannot silently disable every
        legitimate script."""
        import l3_planner
        calls = []

        def _p(content):
            r = mock.Mock()
            r.raise_for_status = mock.Mock()
            r.json = mock.Mock(return_value={"message": {"content": content},
                                             "done_reason": "stop"})
            return r

        def fake_post(url, json=None, timeout=None, **kw):
            calls.append(json)
            return _p(_json.dumps(self._PLAN) if len(calls) == 1
                      else "```javascript\napi.say('fed');\n```")

        with patch.object(l3_planner.requests, "post", side_effect=fake_post), \
                patch.object(l3_planner.trajectory_log, "log_call",
                             return_value="c"), \
                patch.dict(os.environ, {"SCRIPT_BOTS": "Forge",
                                        "SCRIPT_RUNNER_URL": "http://r"},
                           clear=True):
            plan = l3_planner.call_plan("m", "Forge", "keep the furnace fed")

        self.assertEqual(len(calls), 2, "the enabled bot lost its script call")
        self.assertIsNotNone(getattr(plan, "script", None))


class TestAScriptPlanNeedsNoSteps(unittest.TestCase):
    """PTC step 4, PROD 12:21:56Z: "plan missing required field: subtasks".

    A goal with no natural end -- "tell me when it gets dark" -- has no step
    list to give. The prompt offers a script for exactly these, so the
    validator must accept the shape the prompt asks for.
    """

    def _validate(self, d, goal=None):
        import plan_schema
        plan_schema.validate_plan_dict(d, goal=goal)

    def test_a_script_plan_with_no_subtasks_is_accepted(self):
        # KILLS: treating `subtasks` as required for every plan, which failed
        # a goal that never needed steps at all.
        self._validate({"task": "tell me when it gets dark",
                        "wants_script": True})

    def test_a_script_plan_with_an_empty_subtask_list_is_accepted(self):
        # The other shape seen: the model emits the key and leaves it empty
        # rather than omitting it. Same goal, same outcome.
        self._validate({"task": "tell me when it gets dark",
                        "wants_script": True, "subtasks": []})

    def test_a_fenced_script_alone_signals_a_script_plan(self):
        # The prompt has asked for both shapes across versions; a model
        # following the older wording emits a fenced script and no flag.
        self._validate({"task": "tell me when it gets dark",
                        "script": "sleep(600);\napi.result('dawn');"})

    def test_a_step_plan_with_no_subtasks_is_still_rejected(self):
        # The direction that must NOT change. A steppable goal with no steps
        # dispatches nothing while looking successful.
        import plan_schema
        with self.assertRaises(plan_schema.PlanValidationError):
            self._validate({"task": "gather three dirt"})

    def test_a_script_plan_with_malformed_subtasks_is_rejected(self):
        # A script plan may omit steps; it may not ship nonsense in the field.
        # KILLS: `return`ing early on script_plan regardless of what
        # `subtasks` actually holds.
        import plan_schema
        with self.assertRaises(plan_schema.PlanValidationError):
            self._validate({"task": "tell me when it gets dark",
                            "wants_script": True, "subtasks": "three dirt"})

    # ── A missing `task` echo on a script reply ───────────────────────────
    #
    # Prod Mystic 2026-11-22 try 1: "planning failed: plan missing required
    # field: task" -- the model omitted the goal echo on an otherwise complete
    # script reply. The goal text is known to the caller, so it is filled.

    def test_a_script_reply_with_no_task_is_filled_from_the_goal(self):
        # Asserts the FILL, not just that validation passed: the caller builds
        # the Plan from data["task"] (l3_planner.py:614), so a validator that
        # accepted a taskless dict without filling it would validate and then
        # KeyError on the next line.
        d = {"wants_script": True}
        self._validate(d, goal="tell me when it gets dark")
        self.assertEqual(d["task"], "tell me when it gets dark")

    def test_a_step_list_reply_with_no_task_is_still_rejected(self):
        # The direction that must NOT change. A step plan that also omits its
        # own name is a broken reply, and filling it in would let a malformed
        # plan through on the script branch's excuse.
        import plan_schema
        with self.assertRaises(plan_schema.PlanValidationError):
            self._validate({"subtasks": [{"id": 1, "description": "d",
                                          "criteria": "c"}]},
                           goal="gather three dirt")

    def test_a_script_reply_with_no_task_and_no_goal_is_still_rejected(self):
        # No goal to fill from means the field is genuinely absent and cannot
        # be invented. Accepting it here would store a Plan whose task is None.
        import plan_schema
        with self.assertRaises(plan_schema.PlanValidationError):
            self._validate({"wants_script": True})

    def test_a_script_reply_keeps_its_own_task_when_it_has_one(self):
        # The fill must not overwrite a task the model DID provide. A blanket
        # `d["task"] = goal` would discard the model's own (often more
        # specific) wording.
        d = {"task": "watch the sky until dark", "wants_script": True}
        self._validate(d, goal="tell me when it gets dark")
        self.assertEqual(d["task"], "watch the sky until dark")


if __name__ == "__main__":
    unittest.main()

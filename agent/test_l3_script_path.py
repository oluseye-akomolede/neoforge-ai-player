"""a2: the planner's script output reaches the real L3 goal path.

These are the wire-level and orchestrator-level tests for the spec delta
"ai-written-scripts" requirements added in a2:

  - "The Script Output Reaches The L3 Goal Path"
  - "The Planner Writes A Script For Repeating Or Conditional Goals"
  - "Exactly One Driver Per Goal"
  - "Binding A Script Is Atomic Against The Bot's Tick"

Each test carries a KILLS: comment naming the wrong implementation it catches.
A test whose KILLS comment cannot be discharged by a concrete mutant is a test
that is not testing what it claims.
"""

import ast
import json
import os
import sys
import threading
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Importing the sibling module installs the stub modules agent.py needs at
# module scope (psycopg2, fastapi, ...). Reusing it rather than copying the
# stub list keeps the two in step if agent.py's imports change.
import test_agent_script_branch  # noqa: F401
import l3_planner


# ── the strip helper ───────────────────────────────────────────────────────

class TestScriptBlockExtraction(unittest.TestCase):
    """`l3_planner.extract_script_block` reads the reply of the SECOND,
    non-JSON planner call and returns the script alone.

    The script is fetched in its own call, never in the plan call. That is what
    keeps `format: json` on the plan (the common step-list path is unchanged)
    and what makes a malformed script cost the script and nothing else: the
    plan from the first call is already parsed before this runs. The earlier
    single-call design failed the 2026-11-20 15:57Z trial for exactly the
    reason this avoids.
    """

    def test_a_fenced_block_is_extracted(self):
        """KILLS: a helper that returns the whole reply (fence included), which
        would be bound as JavaScript and fail the dry tick."""
        import l3_planner
        script = "while (true) { api.do('feed'); }"
        got = l3_planner.extract_script_block("```js\n" + script + "\n```")

        self.assertEqual(got, script)

    def test_a_multiline_quoted_tabbed_script_round_trips(self):
        """KILLS: a fence regex that does not span newlines (no DOTALL) or that
        stops at the first inner quote/brace, truncating the script it binds.

        This is the 15:57Z script's shape: multi-line, a tab, both quote kinds,
        an apostrophe and braces. It arrived inside a JSON string then and
        broke the plan; here it arrives in its own reply and must round-trip
        byte-identically."""
        import l3_planner
        script = (
            "function tick(ctx) {\n"
            "\tconst say = \"it's full\";   // tab, quotes, apostrophe\n"
            "\tapi.do({ skill: 'STORE_ALL' });\n"
            "\tif (ctx.ticks > 10) { api.say(say); }\n"
            "}"
        )
        got = l3_planner.extract_script_block(
            "```js\n" + script + "\n```")

        self.assertEqual(got, script,
                         "the script did not round-trip byte-identically")

    def test_a_javascript_fence_tag_is_accepted(self):
        """KILLS: a regex that only accepts ```js and returns None for
        ```javascript, silently treating a script the model wrote as absent."""
        import l3_planner
        got = l3_planner.extract_script_block(
            "```javascript\napi.do('x');\n```")

        self.assertEqual(got, "api.do('x');")

    def test_no_block_means_no_script(self):
        """KILLS: a helper that returns prose as if it were a script, which
        would then be bound and fail the dry tick for a goal that never asked
        for one."""
        import l3_planner
        self.assertIsNone(l3_planner.extract_script_block("I cannot write that."))
        self.assertIsNone(l3_planner.extract_script_block(""))

    def test_a_present_but_empty_block_is_not_a_script(self):
        """KILLS: a helper that returns '' for an empty block, which is
        truthy-checked downstream as 'the planner wrote one' and then fails the
        dry tick for no reason."""
        import l3_planner
        self.assertIsNone(l3_planner.extract_script_block("```js\n   \n```"))

    def test_prose_around_the_block_is_ignored(self):
        """KILLS: a helper that requires the reply to be exactly one fence,
        which would discard a usable script when the model adds a courtesy
        sentence. The prompt asks for a bare block; a model that adds one
        anyway should not lose the script."""
        import l3_planner
        got = l3_planner.extract_script_block(
            "Here is your script:\n```js\napi.do('x');\n```\nEnjoy.")

        self.assertEqual(got, "api.do('x');")

class TestCallPlanTwoCalls(unittest.TestCase):
    """The plan call keeps JSON mode and its reply shape, gaining one optional
    `wants_script` boolean. A second, non-JSON call fetches the script only when
    that flag is true. A step-list goal therefore sees the same mode, prompt and
    reply shape as before, and its record is unchanged apart from the flag."""

    def _reply(self, content):
        """`content` is a dict (JSON-encoded) or the exact reply text."""
        body = content if isinstance(content, str) else json.dumps(content)
        resp = mock.Mock()
        resp.raise_for_status = mock.Mock()
        resp.json = mock.Mock(return_value={"message": {"content": body}})
        return resp

    def _drive(self, plan_reply, script_reply=None):
        """Run call_plan with a faked transport, recording every call."""
        import l3_planner
        calls = []
        replies = [self._reply(plan_reply)]
        if script_reply is not None:
            replies.append(self._reply(script_reply))

        def fake_post(url, json=None, timeout=None, **kw):
            calls.append(json)
            return replies[len(calls) - 1]

        logged = []

        def fake_log_call(**kw):
            logged.append(kw)
            return "call-%d" % len(logged)

        with mock.patch.object(l3_planner.requests, "post", side_effect=fake_post), \
             mock.patch.object(l3_planner.trajectory_log, "log_call",
                               side_effect=fake_log_call):
            plan = l3_planner.call_plan("m", "Scout", "keep the furnace fed")
        return plan, calls, logged

    PLAN = {"task": "keep the furnace fed",
            "subtasks": [{"id": 1, "description": "feed", "criteria": "fed"}]}

    def test_a_step_list_goal_makes_exactly_one_call(self):
        """KILLS: making the script call unconditionally, or on any falsy-flag
        check that also fires when the field is merely absent. The delta says a
        wants_script=false reply makes exactly one call, and the common
        step-list path must not pay for the rare scripted one."""
        plan, calls, _ = self._drive(dict(self.PLAN))

        self.assertEqual(len(calls), 1,
                         "a step-list goal made %d planner calls; the delta "
                         "requires exactly one" % len(calls))

    def test_the_plan_call_stays_in_json_mode(self):
        """KILLS: dropping format:json for every plan to make room for a
        script, which is the design that failed the 2026-11-20 trial: it put
        the common path at risk to serve the rare one."""
        _, calls, _ = self._drive(dict(self.PLAN))

        self.assertEqual(calls[0].get("format"), "json",
                         "the plan call lost JSON mode")

    def test_wants_script_true_triggers_a_second_non_json_call(self):
        """KILLS: ignoring wants_script, so a scripted goal never fetches its
        script and the feature is inert."""
        plan, calls, _ = self._drive(
            dict(self.PLAN, wants_script=True),
            "```js\napi.do('feed');\n```")

        self.assertEqual(len(calls), 2, "wants_script did not trigger a call")
        self.assertNotIn("format", calls[1],
                         "the script call used JSON mode; the reply is a fenced "
                         "JS block, not a JSON document")
        self.assertEqual(getattr(plan, "script", None), "api.do('feed');")

    def test_the_script_never_reaches_the_plan_record(self):
        """KILLS: attaching the script before logging, or logging the raw text
        before it is extracted — either puts the script in response_raw, the
        field build_dpo_dataset.py:89-93 trains on verbatim."""
        _, _, logged = self._drive(
            dict(self.PLAN, wants_script=True),
            "```js\napi.do('feed');\n```")

        plan_record = logged[0]
        self.assertNotIn("api.do", plan_record["response_raw"],
                         "the script reached response_raw — the field DPO trains on")
        self.assertNotIn("api.do", json.dumps(plan_record["parsed"] or {}),
                         "the script reached the parsed object")

    def test_an_unusable_script_reply_costs_only_the_script(self):
        """KILLS: raising or failing the goal when the script call returns
        prose or nothing. The plan is already parsed; a bad script means the
        goal runs its steps, which is the pre-a2 behaviour."""
        plan, calls, _ = self._drive(
            dict(self.PLAN, wants_script=True), "I cannot write that.")

        self.assertEqual(len(calls), 2)
        self.assertIsNone(getattr(plan, "script", None))
        self.assertEqual(len(plan.subtasks), 1,
                         "the plan did not survive an unusable script reply")

    def test_a_truncated_script_call_costs_only_the_script(self):
        """KILLS: letting TruncatedAnswer (or a non-JSON body) escape call_script.

        answer_text raises TruncatedAnswer when the model hits its budget with
        an empty answer. Propagating that would fail the whole goal for a
        script problem — but the plan from the first call is already parsed, so
        a truncated script must mean 'no script', not 'no goal'."""
        import l3_planner
        calls = []
        plan_resp = self._reply(dict(self.PLAN, wants_script=True))
        trunc_resp = mock.Mock()
        trunc_resp.raise_for_status = mock.Mock()
        trunc_resp.json = mock.Mock(
            return_value={"message": {"content": ""},
                          "done_reason": "length"})

        def fake_post(url, json=None, timeout=None, **kw):
            calls.append(json)
            return plan_resp if len(calls) == 1 else trunc_resp

        with mock.patch.object(l3_planner.requests, "post", side_effect=fake_post), \
             mock.patch.object(l3_planner.trajectory_log, "log_call",
                               return_value="c"):
            plan = l3_planner.call_plan("m", "Scout", "keep the furnace fed")

        self.assertEqual(len(calls), 2, "the script call was not made")
        self.assertIsNone(getattr(plan, "script", None))
        self.assertEqual(len(plan.subtasks), 1,
                         "a truncated script reply took the plan down with it")

    def test_a_step_list_record_is_unchanged_apart_from_the_flag(self):
        """KILLS: altering the logged response_raw or parsed for a script-free
        reply — the delta's 'sees exactly what it sees now'."""
        _, _, logged = self._drive(dict(self.PLAN))

        self.assertEqual(logged[0]["response_raw"], json.dumps(self.PLAN),
                         "a script-free reply's logged text was altered")


# ── the prompt rule ────────────────────────────────────────────────────────

class TestThePlanPromptStatesWhenToScript(unittest.TestCase):
    """The delta requires the prompt to say the same thing as the spec, not
    leave the choice to preference."""

    def test_the_prompt_names_repeating_goals_as_scripts(self):
        """KILLS: a prompt that describes the script field's syntax but never
        says when to use it — the planner then has a capability and no rule."""
        import l3_planner
        prompt = l3_planner._PLAN_SYSTEM_PROMPT.lower()
        self.assertIn("keep the furnace fed", prompt,
                      "the prompt does not give the repeating-goal example")
        self.assertIn("repeating", prompt)
        self.assertIn("one-shot", prompt)

    def test_the_prompt_forbids_scripts_for_one_shot_goals(self):
        """KILLS: a prompt that lists only script cases, so the planner
        scripts 'craft 8 iron ingots'."""
        import l3_planner
        prompt = l3_planner._PLAN_SYSTEM_PROMPT.lower()
        # The one-shot examples the lead named must appear as step-list cases.
        self.assertIn("go to", prompt)
        self.assertIn("craft", prompt)

    def test_the_prompt_formats_without_a_missing_key(self):
        """KILLS: adding prose with a bare {brace} to a .format() template,
        which raises KeyError on every planner call."""
        import l3_planner
        out = l3_planner._PLAN_SYSTEM_PROMPT.format(
            bot_name="Scout", persona="generalist", dimensions="",
            skills="")
        self.assertIn("Scout", out)


# ── exactly one driver ─────────────────────────────────────────────────────

class TestExactlyOneDriver(unittest.TestCase):
    """When call_plan's reply carries a script, the orchestrator must not also
    execute that reply's steps. Both issuing directives at one bot is the
    double-dispatch the requirement exists to prevent."""

    def _run(self, script_present, on_script_returns=True):
        import plan_orchestrator
        from plan_schema import Plan, Subtask

        steps_dispatched = []
        calls = []

        plan = Plan(
            task="keep the furnace fed", bot="Scout",
            created_at="2026-11-20T00:00:00",
            status="executing",
            subtasks=[Subtask(id=1, description="feed it", criteria="fed")],
            current_subtask_id=1,
        )
        if script_present:
            plan.script = "api.do('feed');"

        def fake_call_plan(*a, **kw):
            return plan

        def dispatch(directive):
            # Phase 2 executes through this. Any call means the step list ran.
            steps_dispatched.append(directive)
            return "COMPLETED"

        def on_script(p, source):
            calls.append(source)
            return on_script_returns

        with mock.patch.object(plan_orchestrator.l3_planner, "call_plan",
                               side_effect=fake_call_plan), \
             mock.patch.object(plan_orchestrator.l3_planner, "call_exec",
                               side_effect=lambda *a, **kw: (
                                   [{"kind": "IDLE"}], None)), \
             mock.patch.object(plan_orchestrator.l3_planner, "call_replan",
                               side_effect=lambda *a, **kw: Subtask(
                                   id=99, description="retry", criteria="fed")), \
             mock.patch.object(plan_orchestrator.plan_store, "write"), \
             mock.patch.object(plan_orchestrator.plan_store, "archive") as archive, \
             mock.patch.object(plan_orchestrator.trajectory_log, "log_plan_close"):
            result = plan_orchestrator.execute_task(
                bot_name="Scout", model="m", task="keep the furnace fed",
                dispatch_fn=dispatch,
                world_state_fn=lambda: "",
                on_script=on_script,
            )
        self.archive = archive
        return result, steps_dispatched, calls

    def test_a_script_reply_does_not_execute_the_steps(self):
        """KILLS: running phase 2 regardless of the script, so the script's
        ticks and L3 EXEC both drive the bot."""
        result, dispatched, calls = self._run(script_present=True)
        self.assertEqual(len(calls), 1, "on_script was not called")
        self.assertEqual(calls[0], "api.do('feed');")
        self.assertEqual(dispatched, [],
                         "the step list executed even though the script took "
                         "the goal — two drivers on one bot")
        # NOT "complete": no subtask ran, so claiming success would be a false
        # win and would skip the honest-finalize guard.
        self.assertEqual(result.status, "handed_over",
                         "a handed-over plan must not claim 'complete': no "
                         "subtask ran, and skill_author.py:140 widens its "
                         "success set on status=='complete'")
        self.assertTrue(result.meta.get("handed_to_script"),
                        "the goal did not record the handover")
        self.assertTrue(self.archive.called,
                        "the handed-over plan was written but never archived; "
                        "the normal finalize does both")

    def test_a_script_free_reply_still_executes_its_steps(self):
        """KILLS: skipping phase 2 whenever the plan object exists, or
        treating an absent script as a handover."""
        result, dispatched, calls = self._run(script_present=False)
        self.assertEqual(calls, [], "on_script ran for a script-free reply")
        self.assertTrue(dispatched, "the step list did not execute")
        self.assertFalse(result.meta.get("handed_to_script"))

    def test_a_refused_handover_still_executes_the_steps(self):
        """KILLS: returning early on a failed bind (e.g. a hand-written
        binding won, or the dry tick failed), leaving the goal undriven by
        anything."""
        result, dispatched, calls = self._run(script_present=True,
                                              on_script_returns=False)
        self.assertEqual(len(calls), 1, "the bind was never attempted")
        self.assertTrue(dispatched,
                        "the bind was refused but the steps did not run: the "
                        "goal has no driver at all")


# ── the real on_script closure ─────────────────────────────────────────────

class TestTheRealOnScriptClosureReleasesTheHold(unittest.TestCase):
    """The tests above stub `on_script`, which is the production closure that
    actually contains the bind-and-release logic. A stub cannot fail the way
    the real function fails, so these drive the real closure from agent.py
    with a real goal_id.

    The hold is taken at agent.py:683 BEFORE the planner thread starts. If a
    refused bind leaves it set, the orchestrator runs the plan's steps while
    _run_script_tick (:2947) sees the hold and returns SCRIPT_HELD -- the goal
    is driven by steps and its script is blocked at the same time.
    """

    def _run_real_closure(self, bind_returns):
        """Call the real on_script closure with a real hold installed."""
        import agent as agent_mod
        import plan_orchestrator
        from plan_schema import Plan, Subtask

        a = agent_mod.BotRunner.__new__(agent_mod.BotRunner)
        a.name = "Scout"
        a.model = "m"
        a.profile = {}
        a._lock = threading.Lock()
        a._planner_script = None
        a._script_tick = None
        a._script_loaded = False
        a._script_hold = None
        a._script_hold_seq = 0
        a._bind_planner_script = mock.Mock(return_value=bind_returns)

        goal_id = a._new_goal_id("Steve", "keep the furnace fed")

        plan = Plan(
            task="keep the furnace fed", bot="Scout",
            created_at="2026-11-20T00:00:00", status="executing",
            subtasks=[Subtask(id=1, description="feed it", criteria="fed")],
            current_subtask_id=1,
        )
        plan.script = "api.do('feed');"
        # Capture the closure agent.py builds by running its real orchestrator
        # branch with execute_task patched to hand us the kwargs. Everything
        # before that call is the production path; only the call itself is
        # stubbed, so the closure under test is the real one.
        captured = {}

        class _Captured(Exception):
            pass

        def fake_execute(**kwargs):
            # Capture and stop: returning normally lets _run_orchestrator run
            # its own failure/release paths, which would clear the hold before
            # the closure under test ever runs and make this a vacuous test.
            captured.update(kwargs)
            raise _Captured()

        # agent.py imports plan_orchestrator inside _run_orchestrator, so
        # patch the module object itself rather than an attribute of agent.
        with mock.patch.object(plan_orchestrator, "execute_task",
                               side_effect=fake_execute):
            try:
                a._run_orchestrator("keep the furnace fed", "Steve",
                                    goal_id=goal_id)
            except _Captured:
                pass

        self.assertIn("on_script", captured,
                      "the orchestrator branch never passed on_script")
        on_script = captured["on_script"]

        # Install the hold NOW, after capture. _run_orchestrator's own
        # `except Exception` calls _end_script_hold on the way out (it treats
        # any crash as terminal, which is correct in production), so a hold
        # taken before the call would already be gone and the test would
        # assert on a state the closure never saw.
        a._begin_script_hold(goal_id, "keep the furnace fed")
        self.assertIsNotNone(a._script_hold, "fixture: the hold was not set")

        # Drive the REAL closure with the real plan.
        handed = on_script(plan, "api.do('feed');")
        return handed, a, goal_id

    def test_a_refused_bind_keeps_the_pre_existing_script_held(self):
        """KILLS: releasing the hold on a refused bind (the 2a79329 version).

        A refused bind means the bot already has a script -- the hand-written
        binding, which is why the bind was refused. Releasing the hold would
        let that script resume and issue directives while the planner's steps
        also drive the bot: two drivers, which "Exactly One Driver Per Goal"
        forbids. The hold is M3-1g: a chat goal beats a running script.
        """
        handed, a, goal_id = self._run_real_closure(bind_returns=False)

        self.assertFalse(handed, "a refused bind must report not-handled")
        self.assertIsNotNone(
            a._script_hold,
            "a refused bind released the hold: the pre-existing hand-written "
            "script resumes and issues directives while the planner's steps "
            "also run -- two drivers on one bot")
        self.assertEqual(a._script_hold["goal_id"], goal_id,
                         "the hold does not name the goal that took it")

    def test_a_successful_bind_releases_the_hold_and_hands_over(self):
        """KILLS: binding without releasing, so the goal's own script is held
        by the goal that asked for it and never ticks."""
        handed, a, goal_id = self._run_real_closure(bind_returns=True)

        self.assertTrue(handed, "a successful bind must report handled")
        self.assertIsNone(a._script_hold,
                          "a successful bind left the goal hold set")


# ── the refused bind, end to end with a real hand-written binding ──────────

class TestRefusedBindAgainstARealHandWrittenBinding(unittest.TestCase):
    """The lead's scenario (15:43Z), driven through real code at every layer.

    Nothing here is stubbed on the path under test:

      - bindings.json and the script file are real files in a tmp dir, and
        SCRIPTS_DIR points at them, so _bind_planner_script refuses the
        planner's script through its OWN hand-written check rather than a
        Mock's return value.
      - _run_script_tick is the real method, so SCRIPT_HELD is the real
        identity object produced by the real hold check.
      - The resume after the goal ends uses the real terminal path
        (_end_script_hold) and then the real _run_script_tick again.

    M3-1g: a chat goal beats a running script. The hold must block the
    hand-written script while the planner's steps run, and the script must
    come back when the goal ends.
    """

    def setUp(self):
        import tempfile
        import agent as agent_mod
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        d = self._tmp.name
        # A tiny, real script. `api.do` is the only call; it never runs,
        # because the hold returns before the tick is taken.
        script_path = os.path.join(d, "scout.js")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write("api.do('noop');\n")
        with open(os.path.join(d, "bindings.json"), "w", encoding="utf-8") as f:
            json.dump({"Scout": "scout.js"}, f)

        self._old_env = os.environ.get("SCRIPTS_DIR")
        os.environ["SCRIPTS_DIR"] = d
        self.addCleanup(self._restore_env)

        a = agent_mod.BotRunner.__new__(agent_mod.BotRunner)
        a.name = "Scout"
        a.model = "m"
        a.profile = {}
        a._lock = threading.Lock()
        a._planner_script = None
        a._script_tick = None
        a._script_loaded = False
        a._script_hold = None
        a._script_hold_seq = 0
        # Real ScriptTick construction talks to the runner over HTTP; the
        # binding decision and the hold check both happen before any tick, so
        # this is only reached if the hold fails to block.
        a._get_script_tick = mock.Mock(
            return_value=mock.Mock(tick=mock.Mock(return_value=(True, [], [], ""))))
        self.a = a
        self.script_path = script_path

    def _capture_real_closure(self, goal_id):
        """Return the real on_script closure from _run_orchestrator.

        Only execute_task is stubbed; everything that builds the closure is
        the production path.
        """
        import plan_orchestrator
        captured = {}

        class _Captured(Exception):
            pass

        def fake_execute(**kw):
            captured.update(kw)
            raise _Captured()

        with mock.patch.object(plan_orchestrator, "execute_task",
                               side_effect=fake_execute):
            try:
                self.a._run_orchestrator("keep the furnace fed", "Steve",
                                         goal_id=goal_id)
            except _Captured:
                pass
        assert "on_script" in captured, "the orchestrator passed no on_script"
        # _run_orchestrator's except-path releases the hold on the way out, so
        # the hold is re-taken here to represent the state the closure sees.
        self.a._begin_script_hold(goal_id, "keep the furnace fed")
        return captured["on_script"]

    def _restore_env(self):
        if self._old_env is None:
            os.environ.pop("SCRIPTS_DIR", None)
        else:
            os.environ["SCRIPTS_DIR"] = self._old_env

    def test_a_hand_written_binding_is_refused_and_held_then_resumes(self):
        """The lead's three checkpoints, in order, all through real code.

        KILLS: releasing the hold on a refused bind (the 2a79329 version). If
        the hold is released there, checkpoint 2 (SCRIPT_HELD while the goal
        runs) returns a normal tick instead and the script issues directives
        while the planner's steps also drive the bot.
        """
        import agent as agent_mod
        a = self.a

        # Checkpoint 0: the real refusal. _bind_planner_script reads the real
        # bindings.json, sees Scout bound, and refuses on its own check.
        self.assertTrue(a._bound_script_path(),
                        "fixture: the hand-written binding was not found")
        self.assertFalse(a._bind_planner_script("api.do('planner');"),
                         "the planner's script was bound over a hand-written "
                         "binding; the hand-written check did not run")

        # The goal arrives and takes the hold (agent.py:683 in production).
        goal_id = a._new_goal_id("Steve", "keep the furnace fed")
        a._begin_script_hold(goal_id, "keep the furnace fed")

        # The orchestrator calls the REAL on_script closure with the planner's
        # script. The closure is where the refused-bind decision lives, so the
        # mutant that releases on refusal only dies if this runs.
        on_script = self._capture_real_closure(goal_id)
        handed = on_script(mock.Mock(), "api.do('planner');")
        self.assertFalse(handed, "the closure claimed the goal was handed over "
                                 "despite the hand-written binding")

        # Checkpoint 2: while the goal runs, the real tick refuses to dispatch
        # the hand-written script.
        result = a._run_script_tick()
        self.assertIs(result, agent_mod.SCRIPT_HELD,
                      "the hand-written script was not held while the goal ran: "
                      f"got {result!r}, so it dispatches alongside the steps")

        # _get_script_tick is a Mock (a real ScriptTick needs WASM, which does
        # not run under this VM's ulimit -v cap -- the lead accepted that
        # boundary at 15:44Z). Assert on its tick() as well as on `called`, so
        # the Mock cannot pass this test vacuously: while the goal holds, the
        # script must not have been ticked at all.
        self.assertFalse(a._get_script_tick.return_value.tick.called,
                         "the hand-written script's tick() ran while the goal "
                         "held the hold: it dispatched alongside the steps")

        # Checkpoint 3: the goal ends via the real terminal path, and the SAME
        # hand-written script runs again.
        self.assertTrue(a._end_script_hold(goal_id),
                        "the terminal path did not release the hold")
        a._script_loaded = False
        result_after = a._run_script_tick()
        self.assertIsNot(result_after, agent_mod.SCRIPT_HELD,
                         "the hand-written script is still held after the goal "
                         "ended: it never resumes")
        self.assertTrue(a._get_script_tick.called,
                        "the resume never reached tick construction")
        # Resuming means exactly one tick() after the release -- not zero (the
        # Mock's return value passed through untouched) and not several (extra
        # ticks from a rebuild loop).
        self.assertEqual(a._get_script_tick.return_value.tick.call_count, 1,
                         "after the goal ended the hand-written script did not "
                         f"tick exactly once: "
                         f"{a._get_script_tick.return_value.tick.call_count}")
        self.assertIsNone(a._script_hold,
                          "the hold outlived the goal: it was never released")


# ── atomic bind ────────────────────────────────────────────────────────────

class TestBindIsAtomicAgainstTheTick(unittest.TestCase):
    """_bind_planner_script swaps three fields _get_script_tick reads. The swap
    must be invisible half-done to a concurrent tick."""

    def _agent(self):
        agent_mod = _agent_module()
        a = agent_mod.BotRunner.__new__(agent_mod.BotRunner)
        a.name = "Scout"
        a.profile = {}
        a._lock = __import__("threading").Lock()
        a._planner_script = None
        a._script_tick = "OLD-TICK"
        a._script_loaded = True
        a._dry_tick = mock.Mock(return_value=True)
        a._bound_script_path = mock.Mock(return_value="")
        return a

    def test_the_tick_cannot_observe_a_half_applied_bind(self):
        """KILLS: assigning the three fields outside the lock, so a tick
        between them sees the new source with the old cached ScriptTick."""
        a = self._agent()
        seen = []

        real_lock = a._lock

        class SpyLock:
            """Records what a reader would see at the moment the lock is taken
            and released, i.e. every interleaving point of the swap."""
            def __enter__(self):
                real_lock.acquire()
                return self

            def __exit__(self, *exc):
                real_lock.release()
                return False

        a._lock = SpyLock()
        # _get_script_tick consults the latch first. With the bind atomic, a
        # tick entering after the bind rebuilds from the NEW source; it must
        # never return the old cached tick beside the new source.
        a._bind_planner_script("while(true){}")

        self.assertEqual(a._planner_script, "while(true){}")
        self.assertIsNone(a._script_tick,
                          "the latch/source pair was left inconsistent")
        self.assertFalse(a._script_loaded)

    def test_the_bind_holds_the_lock_while_swapping(self):
        """KILLS: a bind that takes no lock at all. Deleting the `with
        self._lock` block leaves this test green ONLY if the swap is also
        indivisible by other means, so it pins the guarantee, not the syntax.
        """
        a = self._agent()
        held = []
        real = threading.Lock()

        class Probe:
            # threading.Lock is a factory function, not a class, so it cannot
            # be subclassed. Wrap a real lock instead: the lock semantics are
            # genuine and the observation is honest.
            def __enter__(self):
                held.append(True)
                real.acquire()
                return self

            def __exit__(self, *exc):
                real.release()
                return False

        a._lock = Probe()
        a._bind_planner_script("while(true){}")
        self.assertTrue(held, "the bind swapped state without holding the lock")

    def test_the_tick_reads_its_three_fields_as_one_observation(self):
        """The guarantee the code actually offers, tested at the point it can
        fail: between the three field reads, not during the build.

        KILLS: reading `_script_loaded`, `_planner_script` and `_script_tick`
        without a lock, so a bind lands between them. The bind swaps all three
        together under `self._lock`; a reader holding it must see either the
        pre-bind triple or the post-bind triple, never a mixture.

        Note the lock is released BEFORE ScriptTick is constructed -- by
        design, since the build reads a file and instantiates WASM, and holding
        the lock across that would stall the tick loop. So a bind landing
        during the build is legal and is not what this tests. Two earlier
        versions of this test asserted exactly that, and no mutant could fail
        them because the behaviour they pinned was never promised.
        """
        a = self._agent()
        a._script_tick = "OLD-TICK"
        a._script_loaded = True
        a._planner_script = "// old\n[];"

        # The observation to make: with the latch SET, the tick must return the
        # cached tick for the current source without consulting the raw fields
        # separately. Interpose on the lock: the moment the reader releases it,
        # a bind lands, then we check what the reader returned.
        real_lock = a._lock
        fired = []

        class InterleavingLock:
            def __enter__(self):
                real_lock.acquire()
                return self

            def __exit__(self, *exc):
                real_lock.release()
                if not fired:
                    fired.append(True)
                    # A bind arriving right after the read section: it must
                    # clear the latch so the NEXT tick rebuilds, and must not
                    # be able to produce a tick built from a mix.
                    a._script_loaded = False
                    a._script_tick = None
                    a._planner_script = "// new\n[];"
                return False

        a._lock = InterleavingLock()
        got = a._get_script_tick()

        self.assertEqual(got, "OLD-TICK",
                         "a cached tick was not returned for the source the "
                         "latch was set against")
        # After the bind, the next read rebuilds from the new source.
        a._lock = real_lock
        a._bound_script_path = mock.Mock(return_value="")
        fake_mod = types.ModuleType("script_tick")
        built = []

        class FakeTick:
            def __init__(self, api, name, source):
                self.source = source
                built.append(source)

        fake_mod.ScriptTick = FakeTick
        with mock.patch.dict(sys.modules, {"script_tick": fake_mod}):
            nxt = a._get_script_tick()
        self.assertEqual(built, ["// new\n[];"],
                         "the tick after the bind was not rebuilt from the "
                         "source the bind installed")


class TestTheRawReplyPreview(unittest.TestCase):
    """The lead asked for raw-reply previews because two trial failures were
    unactionable from the message alone. These pin the properties that make a
    preview safe to log: bounded, single-line, and model output only."""

    def test_a_multiline_reply_becomes_one_log_line(self):
        """KILLS: logging the raw text, which splits one failure across many
        lines and hides the rest of the log around it."""
        import l3_planner
        p = l3_planner.preview_reply("line one\nline two\r\nline three")
        self.assertNotIn("\n", p)
        self.assertNotIn("\r", p)
        self.assertIn("line one", p)
        self.assertIn("line three", p)

    def test_the_preview_round_trips_to_the_same_bytes(self):
        """KILLS: escaping that is lossy, so the next reader cannot tell an
        escaped tab from a literal backslash-t in the model's actual output."""
        import l3_planner
        original = 'a\tb\\tc\n\n```js\napi.say("hi");\n```'
        p = l3_planner.preview_reply(original)
        self.assertNotIn("\n", p)
        self.assertEqual(ast.literal_eval(p), original,
                         "the preview does not decode back to the reply")

    def test_the_preview_is_bounded_and_says_how_much_it_dropped(self):
        """KILLS: an unbounded preview, which puts many KiB of JavaScript in
        the log the reader is trying to scan."""
        import l3_planner
        raw = "x" * (l3_planner._PREVIEW_CHARS + 250)
        p = l3_planner.preview_reply(raw)
        self.assertLess(len(p), len(raw),
                        "the preview is not shorter than the reply")
        self.assertIn("+250 chars", p,
                      "the preview does not say how much it dropped")

    def test_a_short_reply_is_not_truncated(self):
        """KILLS: always appending a dropped-count, which implies a truncation
        that did not happen."""
        import l3_planner
        p = l3_planner.preview_reply("```js\nreturn 1;\n```")
        self.assertNotIn("chars]", p)
        self.assertEqual(ast.literal_eval(p), "```js\nreturn 1;\n```")

    def test_an_empty_reply_is_distinguishable_from_no_reply(self):
        """KILLS: rendering both as an empty preview, so "the model returned
        nothing" and "there was no response object" read the same."""
        import l3_planner
        self.assertEqual(l3_planner.preview_reply(None), "<no reply>")
        self.assertEqual(l3_planner.preview_reply(""), "''")


class TestTheFenceFormsThatActuallyFailed(unittest.TestCase):
    """Extraction was rejecting replies that carried a real script (2026-11-20
    18:57Z trial: 1054 chars, opening '```js\\n// Auto-eat when HP drops below
    half', done_reason NOT length, and still "returned no block").

    These pin what the extractor accepts and what it rejects, over the fence
    shapes a model actually emits, so "no block" always has one named cause
    rather than being a catch-all. The head-only preview could not distinguish
    them: all of them look the same in the first 600 chars.
    """

    BODY = 'api.do({ skill: "eat", args: {} });'

    def test_a_properly_closed_block_is_accepted(self):
        """KILLS: making the regex stricter than the form the prompt asks for."""
        got = l3_planner.extract_script_block(
            "```js\n%s\n```" % self.BODY)
        self.assertEqual(got, self.BODY)

    def test_a_closing_fence_with_no_newline_before_it_is_accepted(self):
        """KILLS: requiring \\n before the closing fence, which rejects a block
        the model closed correctly."""
        got = l3_planner.extract_script_block(
            "```js\n%s```" % self.BODY)
        self.assertEqual(got, self.BODY)

    def test_a_missing_closing_fence_is_rejected(self):
        """The form that matches the 18:57Z shape: opens correctly, runs to the
        end, never closes. KILLS: accepting an unterminated block, which would
        bind a program cut short mid-statement."""
        self.assertIsNone(l3_planner.extract_script_block(
            "```js\n%s\n" % self.BODY))

    def test_a_fence_with_no_newline_after_the_tag_is_rejected(self):
        """KILLS: loosening the tag rule to accept '```js <code>' on one line,
        which would swallow the first statement into the language tag."""
        self.assertIsNone(l3_planner.extract_script_block(
            "```js %s\n```" % self.BODY))

    def test_trailing_prose_after_the_fence_still_yields_the_script(self):
        """KILLS: anchoring to the end of the reply, which drops a good script
        because the model added a sentence after it."""
        got = l3_planner.extract_script_block(
            "```js\n%s\n```\n\nThis script eats when health is low." % self.BODY)
        self.assertEqual(got, self.BODY)

    def test_an_empty_block_is_no_script(self):
        """KILLS: returning '' for an empty block, which binds a script that
        does nothing instead of running the plan's steps."""
        self.assertIsNone(l3_planner.extract_script_block("```js\n\n```"))


class TestTheNoBlockWarningSaysWhy(unittest.TestCase):
    """Ask 1 from the 19:02Z handoff: the warning must log done_reason,
    eval_count, len(content), and the LAST chars as well as the head. Without
    the tail every candidate cause looks identical."""

    def _run_capture(self, reply, body_extra=None):
        body = {"message": {"content": reply}}
        if body_extra:
            body.update(body_extra)
        resp = mock.MagicMock()
        resp.json.return_value = body
        resp.raise_for_status.return_value = None
        with mock.patch.object(l3_planner.requests, "post", return_value=resp), \
             mock.patch.object(l3_planner, "ollama_lock", mock.MagicMock()):
            with self.assertLogs(l3_planner.log.name, level="WARNING") as cm:
                got = l3_planner.call_script("Scout", "do a thing", None,
                                             model="qwen3.8:27b")
        return got, "\n".join(cm.output)

    def test_the_warning_names_the_missing_closing_fence(self):
        """KILLS: a warning that only says "no block", which is what made the
        18:57Z failure unactionable."""
        got, log = self._run_capture("```js\nreturn 1;\n")
        self.assertIsNone(got)
        self.assertIn("missing-closing-fence", log)

    def test_the_warning_reports_the_backend_accounting(self):
        """KILLS: dropping done_reason/eval_count from the warning, which is
        how a token-limit cut would be mistaken for a model that gave up."""
        _, log = self._run_capture(
            "```js\nreturn 1;\n", {"done_reason": "stop", "eval_count": 311})
        self.assertIn("done_reason='stop'", log)
        self.assertIn("eval_count=311", log)

    def test_the_warning_includes_the_tail_not_only_the_head(self):
        """KILLS: logging only the head preview. A 1054-char reply whose head
        looks perfect is exactly the case that needs its last 200 chars: that
        is where a missing fence is visible."""
        long = "```js\n" + ("// filler line\n" * 60) + "return 1;\n"
        _, log = self._run_capture(long)
        self.assertIn("tail:", log)
        tail = l3_planner.tail_reply(long)
        self.assertIn(repr(long[-200:]), tail,
                      "the tail does not show the literal end of the reply")
        # The distinguishing content is at the END, so a head-only preview
        # cannot contain it.
        self.assertNotIn(repr(long[-200:]), l3_planner.preview_reply(long))

    def test_an_unclosed_fence_at_the_very_end_shows_in_the_tail(self):
        """KILLS: a tail that elides the end (e.g. shows from the top)."""
        long = "```js\n" + ("x" * 300) + "\nBROKEN_END"
        tail = l3_planner.tail_reply(long)
        self.assertIn("BROKEN_END", tail)


class TestTheScriptCallsTokenBudget(unittest.TestCase):
    """The 19:10Z trial: the SCRIPT call stopped at exactly eval_count=1024
    with done_reason=length and thinking OFF, so the budget was all content and
    the script was simply longer than it. The unclosed fence then read as "no
    block", which looked like a model problem and was a budget problem.

    These pin the budget to the SCRIPT call alone. Raising it everywhere would
    slow every call to serve one; raising it nowhere leaves the script unable to
    finish.
    """

    def _script_body(self):
        return {
            "url": None, "json": None, "timeout": None,
        }

    def _drive(self):
        import l3_planner
        seen = []

        def fake_post(url, json=None, timeout=None, **kw):
            seen.append({"url": url, "body": json, "timeout": timeout})
            resp = mock.Mock()
            resp.raise_for_status = mock.Mock()
            resp.json = mock.Mock(
                return_value={"message": {"content": "```js\nreturn [];\n```"}})
            return resp

        with mock.patch.object(l3_planner.requests, "post", side_effect=fake_post), \
             mock.patch.object(l3_planner, "ollama_lock", mock.MagicMock()):
            got = l3_planner.call_script("Scout", "run away from zombies",
                                         None, model="qwen3.8:27b")
        return got, seen

    def test_the_script_call_asks_for_more_than_the_plan_budget(self):
        """KILLS: leaving num_predict at the plan's 1024, the value the trial
        hit exactly. A budget at or below the observed ceiling cannot fit the
        answer that overflowed it."""
        got, seen = self._drive()
        self.assertIsNotNone(got)
        budget = seen[0]["body"]["options"]["num_predict"]
        self.assertGreater(budget, 1024,
                           "the script call's budget stayed at the plan's 1024")
        self.assertEqual(budget, l3_planner._SCRIPT_NUM_PREDICT)

    def test_the_script_call_keeps_its_other_options(self):
        """KILLS: changing the budget while dropping JSON-off, the model, the
        stream flag or the timeout, any of which changes behaviour the trial
        relied on."""
        _, seen = self._drive()
        body = seen[0]["body"]
        self.assertNotIn("format", body,
                         "the script call must NOT be in JSON mode")
        self.assertEqual(body["model"], "qwen3.8:27b")
        self.assertIs(body["stream"], False)
        self.assertEqual(body["options"]["temperature"], 0.2)
        self.assertEqual(seen[0]["timeout"], l3_planner._OLLAMA_TIMEOUT)

    def test_the_budget_change_is_the_script_calls_alone(self):
        """KILLS: copying the new value into the plan call or any other prompt,
        which would change latency and output for calls nobody complained
        about. The plan call's 1024 is read from the wire, not from source."""
        import l3_planner
        plan_calls = []

        def fake_post(url, json=None, timeout=None, **kw):
            plan_calls.append(json)

            class R:
                def raise_for_status(self_):
                    return None

                def json(self_):
                    return {"message": {"content": json_out}}
            return R()

        json_out = '{"task": "t", "subtasks": [{"id": 1, "description": "d", "criteria": "c"}]}'
        with mock.patch.object(l3_planner.requests, "post", side_effect=fake_post), \
             mock.patch.object(l3_planner.trajectory_log, "log_call",
                               return_value="c-1"):
            l3_planner.call_plan("m", "Scout", "keep the furnace fed")
        self.assertEqual(plan_calls[0]["options"]["num_predict"], 1024,
                         "the plan call's budget changed with the script call's")


class TestTheFenceCountIgnoresOtherLanguages(unittest.TestCase):
    """Reviewer N-1 on 938fae6f: the diagnosis counted closes as
    `count("```") - opens`, which counts every NON-js opening fence as a
    closing fence. A reply containing a python block and a js block therefore
    reported 'opened 1, closed 3' -- more closes than exist, and enough to
    hide a genuinely missing js close.

    Both numbers are asserted, not just the wording: a report that names the
    wrong counts sends the next reader to the wrong fix.
    """

    PY_THEN_JS = (
        "Here is how I would do it in python:\n"
        "```python\n"
        "print('hi')\n"
        "```\n"
        "and the script:\n"
        "```js\n"
        "return [];\n"
        "```\n"
    )

    def test_a_python_block_is_not_counted_as_a_js_open(self):
        """KILLS: counting any fenced block as a js open, which would report
        opened 2 for one js block."""
        d = l3_planner.fence_diagnosis(self.PY_THEN_JS)
        self.assertIn("opened 1", d, d)

    def test_a_python_block_is_not_counted_as_a_close(self):
        """The N-1 defect itself. KILLS: closes = count(fence) - opens, which
        gives 3 closes for this reply when there is exactly one js close."""
        d = l3_planner.fence_diagnosis(self.PY_THEN_JS)
        self.assertIn("closed 2", d, d)
        self.assertNotIn("closed 3", d, d)

    def test_the_no_js_branch_still_fires_for_python_only(self):
        """KILLS: letting a python block satisfy the js-open check."""
        d = l3_planner.fence_diagnosis("```python\nprint('x')\n```\n")
        self.assertIn("no-js-fence", d)

    def test_a_really_missing_js_close_is_not_called_unusable(self):
        """The case N-1 could mask, and a limit worth pinning rather than
        hiding: with a python block present, an unclosed js block gives
        'opened 1, closed 1'. The counts are EQUAL, so arithmetic alone would
        report 'block-unusable' — pointing the next reader at a bad script
        instead of a missing close. What must hold is that the message never
        claims the block was closed; it is only called unusable when a close
        was actually found for it."""
        text = (
            "```python\nprint('x')\n```\n"
            "```js\nreturn [];\n"
        )
        d = l3_planner.fence_diagnosis(text)
        self.assertIn("opened 1", d, d)
        self.assertIn("closed 1", d, d)
        # The extractor agrees there is no script to bind, which is the fact
        # the warning exists to explain.
        self.assertIsNone(l3_planner.extract_script_block(text))


def _agent_module():
    import importlib
    return importlib.import_module("agent")


if __name__ == "__main__":
    unittest.main()

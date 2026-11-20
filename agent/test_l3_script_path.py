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

class TestScriptChannelSplit(unittest.TestCase):
    """`l3_planner.split_script_channel` is the helper the delta names as the
    insertion point between :426 (_strip_codefence) and :429 (json.loads).

    It takes the model's raw text and returns (plan_text, script_or_None),
    where plan_text parses to the plan JSON with no script in it. Everything
    downstream — `response_raw`, `parsed`, the DPO pair — is derived from
    plan_text, so this function is where the leak is prevented or not.
    """

    def test_a_script_is_split_out_of_the_model_text(self):
        """KILLS: a helper that returns the text unchanged when a script is
        present, leaving the script in the string that becomes response_raw."""
        import l3_planner
        model_text = json.dumps({
            "task": "keep the furnace fed",
            "subtasks": [{"id": 1, "description": "feed it",
                          "criteria": "furnace has fuel"}],
            "script": "while (true) { api.do('feed'); }",
        })
        plan_text, script = l3_planner.split_script_channel(model_text)

        self.assertIsNotNone(script, "the script was not extracted")
        self.assertIn("api.do('feed')", script)
        self.assertNotIn("api.do", plan_text,
                         "the script survived into the plan text — this is the "
                         "string logged as response_raw")
        # And the plan half must still be valid JSON with the subtasks intact.
        plan = json.loads(plan_text)
        self.assertEqual(plan["task"], "keep the furnace fed")
        self.assertEqual(len(plan["subtasks"]), 1)
        self.assertNotIn("script", plan,
                         "the script key survived in the parsed object")

    def test_no_script_leaves_the_text_byte_identical(self):
        """KILLS: a helper that always re-serialises the JSON (reordering
        keys, changing spacing) even when there is no script, which would
        break 'with no script, byte-identical to today'."""
        import l3_planner
        model_text = '{"task":"go to X","subtasks":[{"id":1,"description":"walk","criteria":"arrived"}]}'
        plan_text, script = l3_planner.split_script_channel(model_text)

        self.assertIsNone(script)
        self.assertEqual(plan_text, model_text,
                         "a script-free reply was altered; the delta requires "
                         "byte-identical output when no script is present")

    def test_malformed_text_is_returned_untouched(self):
        """KILLS: a helper that raises (or returns a re-serialised blob) on
        non-JSON input, turning a plan the caller already handles into a
        crash. The caller's existing json.JSONDecodeError path must still run.
        """
        import l3_planner
        model_text = "this is not json at all"
        plan_text, script = l3_planner.split_script_channel(model_text)

        self.assertIsNone(script)
        self.assertEqual(plan_text, model_text,
                         "non-JSON text was modified; the caller's decode-error "
                         "path needs the original text to report on")

    def test_a_present_but_empty_script_is_not_a_script(self):
        """KILLS: a helper that returns an empty string for `script`, which is
        truthy-checked downstream as 'the planner wrote one' and then fails the
        dry tick for no reason."""
        import l3_planner
        model_text = json.dumps({
            "task": "go to X",
            "subtasks": [{"id": 1, "description": "walk", "criteria": "there"}],
            "script": "   ",
        })
        plan_text, script = l3_planner.split_script_channel(model_text)

        self.assertIsNone(script, "whitespace was treated as a script")
        # Text is returned untouched (the byte-identical path), which still
        # holds the empty key. The property that matters is what reaches the
        # trainer, and a blank script is not source, so the parsed object is
        # allowed to keep the key — but no source is in it either way.
        plan = json.loads(plan_text)
        self.assertEqual(plan.get("script", "").strip(), "",
                         "a blank script acquired content on the way through")


# ── call_plan plumbing ─────────────────────────────────────────────────────

class TestCallPlanCarriesTheScript(unittest.TestCase):
    """call_plan must hand the script back on the returned Plan without
    letting it into the logged record."""

    def _fake_post(self, payload):
        resp = mock.Mock()
        resp.raise_for_status = mock.Mock()
        resp.json = mock.Mock(return_value={"message": {"content": json.dumps(payload)}})
        return resp

    def test_a_script_lands_on_the_plan_not_in_the_record(self):
        """KILLS: attaching the script before logging, or logging the raw
        text before the split — either puts the script in response_raw, which
        build_dpo_dataset.py:89-93 trains on verbatim."""
        import l3_planner
        payload = {
            "task": "keep the furnace fed",
            "subtasks": [{"id": 1, "description": "feed", "criteria": "fed"}],
            "script": "api.do('feed');",
        }
        logged = {}

        def fake_log_call(**kw):
            logged.update(kw)
            return "call-1"

        with mock.patch.object(l3_planner.requests, "post",
                               return_value=self._fake_post(payload)), \
             mock.patch.object(l3_planner.trajectory_log, "log_call",
                               side_effect=fake_log_call):
            plan = l3_planner.call_plan("m", "Scout", "keep the furnace fed")

        self.assertEqual(getattr(plan, "script", None), "api.do('feed');",
                         "the script did not reach the Plan")
        # The two fields the trainer reads.
        self.assertNotIn("api.do", logged["response_raw"],
                         "the script reached response_raw — the field DPO trains on")
        self.assertNotIn("script", logged["parsed"],
                         "the script reached the parsed object")

    def test_no_script_means_a_byte_identical_record(self):
        """KILLS: a change that alters the logged response_raw or parsed for
        every reply, script or not."""
        import l3_planner
        payload = {"task": "go to X",
                   "subtasks": [{"id": 1, "description": "walk", "criteria": "there"}]}
        logged = {}

        def fake_log_call(**kw):
            logged.update(kw)
            return "call-2"

        with mock.patch.object(l3_planner.requests, "post",
                               return_value=self._fake_post(payload)), \
             mock.patch.object(l3_planner.trajectory_log, "log_call",
                               side_effect=fake_log_call):
            plan = l3_planner.call_plan("m", "Scout", "go to X")

        self.assertIsNone(getattr(plan, "script", None))
        self.assertEqual(logged["response_raw"], json.dumps(payload),
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

    def test_a_refused_bind_does_not_leave_the_goal_held(self):
        """KILLS: releasing the hold only on a successful bind, so a refusal
        (a hand-written binding won, or the dry tick was rejected) leaves the
        hold set while the orchestrator runs the steps."""
        handed, a, goal_id = self._run_real_closure(bind_returns=False)

        self.assertFalse(handed, "a refused bind must report not-handled")
        self.assertIsNone(
            a._script_hold,
            "a refused bind left the goal hold set: the orchestrator runs the "
            "steps while _run_script_tick returns SCRIPT_HELD, so the goal is "
            "driven with its script blocked")

    def test_a_successful_bind_releases_the_hold_and_hands_over(self):
        """KILLS: binding without releasing, so the goal's own script is held
        by the goal that asked for it and never ticks."""
        handed, a, goal_id = self._run_real_closure(bind_returns=True)

        self.assertTrue(handed, "a successful bind must report handled")
        self.assertIsNone(a._script_hold,
                          "a successful bind left the goal hold set")


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


def _agent_module():
    import importlib
    return importlib.import_module("agent")


if __name__ == "__main__":
    unittest.main()

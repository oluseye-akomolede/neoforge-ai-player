"""Tests for the M2 script path's integration into Agent._loop (task 3.2).

These do NOT run a bot. They exercise `_run_script_tick` with a stub ScriptTick
and assert the two properties the loop depends on:

  handled=True  -> True  (the loop `continue`s, planner skipped)
  anything else -> False (the loop falls through, planner runs unchanged)

The second is the task 7.2 guarantee, and it is the one that fails silently:
a script path that returns True on an error would suppress the planner and
leave the bot standing still with no error anyone notices.

`Agent` is constructed through `__new__` and given only the attributes this
path touches, because the real constructor opens sockets and threads. That is
deliberate: importing agent.py needs psycopg2/uvicorn absent, so this module is
skipped when those are missing rather than failing the suite in a clean seat.
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


class _Any:
    def __init__(self, *a, **k):
        pass

    def __call__(self, *a, **k):
        return _Any()

    def __iter__(self):
        return iter(())

    def __getattr__(self, n):
        return _Any()


class _BaseModel:
    def __init__(self, *a, **k):
        pass

    def __init_subclass__(cls, **k):
        pass


class _Mod(types.ModuleType):
    def __getattr__(self, n):
        if n.startswith("__"):
            raise AttributeError(n)
        return _BaseModel if n == "BaseModel" else _Any()


# agent.py imports the dashboard (fastapi), the DB (psycopg2) and uvicorn at
# module scope. None of that is exercised by the tick branch, but the import
# must succeed for the branch to be reachable by a test at all. Stubbing the
# modules lets the REAL agent.py load, so the REAL method runs -- unlike the
# first version of this file, which skipped all five tests in a clean seat and
# printed OK. A suite that skips everything is not evidence.
_STUBS = (
    "psycopg2", "psycopg2.extras", "uvicorn", "fastapi", "fastapi.responses",
    "fastapi.staticfiles", "fastapi.middleware", "fastapi.middleware.cors",
    "pydantic", "starlette.responses", "python_multipart",
)
for _m in _STUBS:
    sys.modules.setdefault(_m, _Mod(_m))
sys.modules["psycopg2"].extras = sys.modules["psycopg2.extras"]


def _agent_module():
    return importlib.import_module("agent")


class ScriptTickBranchTest(unittest.TestCase):

    def setUp(self):
        agent_mod = _agent_module()
        self.agent_mod = agent_mod
        # __new__ skips __init__ (which starts threads / opens sockets). We set
        # the exact attributes _run_script_tick reads.
        self.a = agent_mod.BotRunner.__new__(agent_mod.BotRunner)
        self.a.name = "Scout"
        self.a.profile = {}
        self.a._script_tick = None
        self.a._script_loaded = True   # do not go looking for a profile script
        # Script actions go through the orchestrator, not _run_directive: it
        # is the dispatcher that knows the agent-side vocabulary (EQUIP,
        # DROP, VAULT_*, ...) as well as mod directives.
        self.a._l3_orchestrator_dispatch = mock.Mock(
            return_value="COMPLETED STORE_ALL {'stored': 1}")
        self.a._run_directive = mock.Mock(return_value={"success": True})

    def _with_tick(self, tick_result):
        ticks = []

        class Stub:
            def tick(_self):
                ticks.append(1)
                return tick_result

        self.a._script_tick = Stub()
        return ticks

    def test_handled_actions_skip_the_planner(self):
        # The fixture is the shape `bind_actions` ACTUALLY returns --
        # `{"kind": KIND, **allowed_args}` (action_binding.py:82) -- not a
        # `{"directive": {...}}` wrapper. The previous fixture used the wrapper,
        # which no producer emits, so this test passed while the consumer read
        # `act["directive"]` -> None -> `continue`, executing nothing. A fixture
        # that does not match the producer is a test of the fixture.
        self._with_tick((True, [{"kind": "STORE_ALL"}], [], "ok"))
        self.assertTrue(self.a._run_script_tick(),
                        "a handled tick must tell the loop to skip the planner")
        self.a._l3_orchestrator_dispatch.assert_called_once_with({"kind": "STORE_ALL"})

    def test_bound_arguments_survive_the_hop_to_the_dispatcher(self):
        # A bound action carries its allowed args beside `kind`. All of them must
        # reach the dispatcher, or a script's coordinates/counts are silently
        # dropped between binding and execution.
        self._with_tick((True, [{"kind": "STORE_ALL", "x": "10", "y": "64", "z": "10"}],
                         [], "ok"))
        self.assertTrue(self.a._run_script_tick())
        self.a._l3_orchestrator_dispatch.assert_called_once_with(
            {"kind": "STORE_ALL", "x": "10", "y": "64", "z": "10"})

    def test_agent_side_kinds_reach_the_orchestrator(self):
        # EQUIP_ALL is NOT a mod directive -- the mod has no such directive
        # type. Posted as one it fails, and the failure used to consume the
        # tick. The orchestrator maps it to api.equip_all (agent.py:901).
        self._with_tick((True, [{"kind": "EQUIP_ALL"}], [], "ok"))
        self.assertTrue(self.a._run_script_tick())
        self.a._l3_orchestrator_dispatch.assert_called_once_with({"kind": "EQUIP_ALL"})

    def test_a_refused_action_does_not_consume_the_tick(self):
        # The bot must not go quiet because a script asked for impossible work.
        self.a._l3_orchestrator_dispatch = mock.Mock(
            return_value="FAILED EQUIP_ALL no armor")
        self._with_tick((True, [{"kind": "EQUIP_ALL"}], [], "ok"))
        self.assertFalse(self.a._run_script_tick(),
                         "a refused action consumed the tick - the planner never runs")
        self.a._l3_orchestrator_dispatch.assert_called_once()

    def test_one_refusal_among_successes_still_counts_as_handled(self):
        self.a._l3_orchestrator_dispatch = mock.Mock(
            side_effect=["COMPLETED STORE_ALL ok", "FAILED DROP no dirt"])
        self._with_tick((True, [{"kind": "STORE_ALL"}, {"kind": "DROP", "target": "dirt"}],
                         [], "ok"))
        self.assertTrue(self.a._run_script_tick(),
                        "a real action ran; the planner must be suppressed")

    def test_every_failure_falls_through_to_the_planner(self):
        # Each of these must return False. A True here silences the planner.
        cases = {
            "fallback timeout": (False, [], [], "timeout"),
            "fallback refused": (False, [], [], "refused"),
            "fallback error": (False, [], [], "error"),
            "script chose silence": (True, [], [], "ok"),
            "all actions refused": (True, [], ["refused X"], "ok"),
        }
        for label, result in cases.items():
            with self.subTest(label):
                self.a._l3_orchestrator_dispatch.reset_mock()
                self._with_tick(result)
                self.assertFalse(self.a._run_script_tick(),
                                 f"{label} suppressed the planner")
                self.a._l3_orchestrator_dispatch.assert_not_called()

    def test_no_script_means_no_runner_call(self):
        ticks = self._with_tick((True, [], [], "ok"))
        self.a._script_tick = None
        self.assertFalse(self.a._run_script_tick())
        self.assertEqual(ticks, [], "ran a tick for a bot with no script")

    def test_an_exception_in_the_script_path_never_kills_the_loop(self):
        class Boom:
            def tick(_self):
                raise RuntimeError("runner exploded")

        self.a._script_tick = Boom()
        self.assertFalse(self.a._run_script_tick(),
                         "an exception must fall through, not propagate")

    def test_a_refusal_is_logged_not_swallowed(self):
        self._with_tick((True, [], ["refused DROP"], "ok"))
        with mock.patch("builtins.print") as p:
            self.a._run_script_tick()
        printed = " ".join(str(c.args[0]) for c in p.call_args_list if c.args)
        self.assertIn("refused DROP", printed,
                      "a refused action vanished with no trace")


class BindingsTest(unittest.TestCase):
    """The bot-to-script map, tested against a real file on disk.

    Every test here writes an actual bindings.json into a temp SCRIPTS_DIR and
    lets the real `_bound_script_path` read it. That is deliberate: the first
    version of the script path set `_script_tick` directly in setUp, so a mutant
    that bound EVERY bot to scout.js survived the whole suite -- nothing ever
    exercised the lookup. A test that constructs the object under test cannot
    fail on the question of whether the object is found.
    """

    def setUp(self):
        agent_mod = _agent_module()
        self.agent_mod = agent_mod
        self.tmp = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"SCRIPTS_DIR": self.tmp})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (open(os.path.join(self.tmp, "scout.js"), "w", encoding="utf-8")
         .write("// scout\n"))

    def _runner(self, name):
        a = self.agent_mod.BotRunner.__new__(self.agent_mod.BotRunner)
        a.name = name
        a.profile = {}
        a._script_tick = None
        a._script_loaded = False
        return a

    def _bind(self, mapping):
        with open(os.path.join(self.tmp, "bindings.json"), "w",
                  encoding="utf-8") as f:
            json.dump(mapping, f)

    def test_a_bound_bot_gets_its_script(self):
        self._bind({"Scout": "scout.js"})
        path = self._runner("Scout")._bound_script_path()
        self.assertEqual(path, os.path.join(self.tmp, "scout.js"))

    def test_an_unbound_bot_gets_no_script(self):
        # This is the assertion the surviving mutant walked through: with
        # {"Scout": ...} in the map, Miner must still resolve to nothing.
        self._bind({"Scout": "scout.js"})
        self.assertIsNone(self._runner("Miner")._bound_script_path())

    def test_no_bindings_file_means_no_script(self):
        self.assertIsNone(self._runner("Scout")._bound_script_path())

    def test_the_module_level_door_agrees_with_the_method_in_every_state(self):
        """`self.agent_mod.bound_script_path(name)` must answer exactly what the tick asks.

        Review 2026-11-11: the run plan told an operator to run
        `python3 -c 'import agent; print(agent._bound_script_path("Scout"))'`.
        That raises AttributeError -- the resolver is an instance method -- at
        the one point in the run that separates an inert deployment from one
        quietly running the wrong file, so a typo there costs a live judgement
        call about whether the feature or the command broke.

        The risk of adding a module-level door is that it becomes a second
        implementation that drifts from the first. So this asserts agreement
        across the states rather than testing the wrapper in isolation.

        Review 2026-11-11 F: the first version of this claimed four states were
        enough to catch a reimplementation, and that claim was false. A
        faithful copy of the happy path agrees on bound / unbound / no-file /
        C1. The resolver also has four GUARDS -- traversal, a non-dict bindings
        file, a non-str binding, an empty string -- and a reimplementation that
        dropped any of them agreed on all four of those states. Green tests
        asserting a property they cannot test are worse than absent ones: they
        are what stops the next person checking. The guard states below are
        constructed so that dropping a guard diverges here.
        """
        # 1. bound
        self._bind({"Scout": "scout.js"})
        self.assertEqual(self.agent_mod.bound_script_path("Scout"),
                         self._runner("Scout")._bound_script_path())
        self.assertTrue(self.agent_mod.bound_script_path("Scout").endswith("scout.js"))

        # 2. in the file but not in the map
        self.assertEqual(self.agent_mod.bound_script_path("Miner"),
                         self._runner("Miner")._bound_script_path())
        self.assertIsNone(self.agent_mod.bound_script_path("Miner"))

        # 3. no bindings file at all
        os.unlink(os.path.join(self.tmp, "bindings.json"))
        self.assertEqual(self.agent_mod.bound_script_path("Scout"),
                         self._runner("Scout")._bound_script_path())
        self.assertIsNone(self.agent_mod.bound_script_path("Scout"))

        # 4. the C1 refusal: SCRIPTS_DIR unset, a baked map present. Both must
        # refuse rather than read the image's copy.
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SCRIPTS_DIR", None)
            baked = os.path.join(os.path.dirname(self.agent_mod.__file__), "scripts")
            if os.path.isdir(baked):
                self.assertIsNone(self.agent_mod.bound_script_path("Scout"))
            self.assertEqual(self.agent_mod.bound_script_path("Scout"),
                             self._runner("Scout")._bound_script_path())

    def test_the_door_agrees_on_the_states_the_guards_exist_for(self):
        """The four guard states, which is where a reimplementation diverges.

        Each row here is a value the resolver explicitly refuses. A wrapper
        that reimplemented the happy path without one of these guards would
        return a path where the method returns None -- and would pass every
        state in the test above. This test is the control that makes that
        claim (in the docstring above) true rather than decorative.
        """
        cases = [
            # (label, bindings object, bot name)
            ("traversal", {"Scout": "../../etc/passwd"}, "Scout"),
            ("absolute-ish", {"Scout": "/etc/passwd"}, "Scout"),
            ("dotfile", {"Scout": ".hidden.js"}, "Scout"),
            ("non-str binding", {"Scout": 42}, "Scout"),
            ("empty binding", {"Scout": ""}, "Scout"),
        ]
        for label, bindings, bot in cases:
            with self.subTest(label=label):
                self._bind(bindings)
                door = self.agent_mod.bound_script_path(bot)
                method = self._runner(bot)._bound_script_path()
                self.assertEqual(
                    door, method,
                    f"{label}: door and method disagree ({door!r} vs {method!r})")
                self.assertIsNone(
                    door, f"{label}: both must refuse, got {door!r}")

        # A bindings file that is not an object at all: a JSON array.
        with open(os.path.join(self.tmp, "bindings.json"), "w") as f:
            json.dump(["Scout", "scout.js"], f)
        self.assertEqual(self.agent_mod.bound_script_path("Scout"),
                         self._runner("Scout")._bound_script_path())
        self.assertIsNone(self.agent_mod.bound_script_path("Scout"))

        # And a syntactically invalid file, which takes the ValueError arm.
        with open(os.path.join(self.tmp, "bindings.json"), "w") as f:
            f.write("{not json")
        self.assertEqual(self.agent_mod.bound_script_path("Scout"),
                         self._runner("Scout")._bound_script_path())
        self.assertIsNone(self.agent_mod.bound_script_path("Scout"))

    def test_unset_scripts_dir_does_not_fall_back_to_the_image_copy(self):
        """SCRIPTS_DIR unset must disable script mode, and say so.

        Review 2026-11-11 C1. Before this, the resolver fell back to
        `dirname(__file__)/scripts` -- the copy baked into the image. Measured
        on TEST: with the env unset, Scout bound the image's bindings.json and
        every log line read normal, so a pod whose ConfigMap mount had failed
        ran a stale script that looked healthy. That is the one configuration
        where the failure hides, so it gets its own test rather than a comment.

        The image no longer carries scripts/ (Dockerfile), but the guard is what
        makes the removal durable: a future COPY that reintroduces the file
        fails here instead of at 3am on TEST.
        """
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SCRIPTS_DIR", None)
            with mock.patch.object(self.agent_mod, "__file__",
                                   os.path.join(self.tmp, "agent.py")):
                # Plant exactly what the image used to bake in.
                baked = os.path.join(self.tmp, "scripts")
                os.makedirs(baked, exist_ok=True)
                with open(os.path.join(baked, "bindings.json"), "w",
                          encoding="utf-8") as f:
                    json.dump({"Scout": "scout.js"}, f)
                with open(os.path.join(baked, "scout.js"), "w",
                          encoding="utf-8") as f:
                    f.write("// stale\n")
                with mock.patch("builtins.print") as p:
                    path = self._runner("Scout")._bound_script_path()
        self.assertIsNone(
            path, "with SCRIPTS_DIR unset the baked-in map must not bind")
        printed = " ".join(str(c.args[0]) for c in p.call_args_list if c.args)
        self.assertIn("SCRIPTS_DIR is not set", printed,
                      "declining the fallback must be loud, not silent")

    def test_a_malformed_bindings_file_is_logged_and_ignored(self):
        with open(os.path.join(self.tmp, "bindings.json"), "w",
                  encoding="utf-8") as f:
            f.write("{not json")
        with mock.patch("builtins.print") as p:
            self.assertIsNone(self._runner("Scout")._bound_script_path())
        printed = " ".join(str(c.args[0]) for c in p.call_args_list if c.args)
        self.assertIn("cannot read", printed,
                      "a broken bindings file must not be silent")

    def test_a_binding_may_not_escape_the_scripts_dir(self):
        self._bind({"Scout": "../../etc/passwd"})
        with mock.patch("builtins.print") as p:
            self.assertIsNone(self._runner("Scout")._bound_script_path())
        printed = " ".join(str(c.args[0]) for c in p.call_args_list if c.args)
        self.assertIn("bad binding", printed)

    def test_the_full_path_reads_the_bound_file(self):
        # End to end through the real loader: binds Scout, then confirms the
        # tick was built with scout.js's text. A break anywhere in lookup ->
        # open -> ScriptTick shows up here.
        self._bind({"Scout": "scout.js"})
        a = self._runner("Scout")
        a.api = mock.Mock()
        tick = a._get_script_tick()
        self.assertIsNotNone(tick)
        self.assertEqual(tick._source, "// scout\n")


class ScriptObservabilityTest(unittest.TestCase):
    """M3-1c: the script's own logs and its idle outcome must reach the log.

    These go through the REAL ScriptTick with a fake transport that returns the
    runner's actual wire shape (`src/main.js:145-156`), not a hand-built tuple.
    The M3-1b lesson was that a fixture which feeds the consumer directly proves
    nothing about the producer; a stub tick returning a bare tuple would have
    passed over the missing `logs` relay because the stub never had logs.
    """

    def setUp(self):
        agent_mod = _agent_module()
        self.agent_mod = agent_mod
        self.a = agent_mod.BotRunner.__new__(agent_mod.BotRunner)
        self.a.name = "Scout"
        self.a.profile = {}
        self.a._l3_orchestrator_dispatch = mock.Mock(
            return_value="COMPLETED STORE_ALL {'stored': 1}")

    def _real_tick(self, payload):
        """One real ScriptTick whose runner answers `payload`."""
        import script_tick

        def _post(path, data=None, **kw):
            return payload

        st = script_tick.ScriptTick(_Any(), "Scout", "api.log('hi')", post=_post)
        self.a._script_tick = st
        self.a._script_loaded = True
        return st

    def _wire(self, **over):
        """The runner's documented tick response shape, from src/main.js."""
        base = {"contract_version": 1, "status": "ok", "script_revision": "r",
                "actions": [], "cpu_ms": 1, "wall_ms": 2, "host_calls": 0,
                "heap_peak_bytes": 0, "memory_out": None, "logs": [],
                "logs_dropped": 0, "cold": False}
        base.update(over)
        return base

    def test_a_script_log_line_reaches_the_agent_log(self):
        self._real_tick(self._wire(logs=["hi from scout"]))
        with mock.patch("builtins.print") as p:
            self.a._run_script_tick()
        out = " ".join(str(c) for c in p.call_args_list)
        self.assertIn("[Scout/script] log: hi from scout", out,
                      "the runner returned a log line and the agent dropped it")

    def test_no_logs_prints_no_log_lines(self):
        # The control: a quiet script must not look like a script whose lines
        # were swallowed. Without this, the test above could pass on any
        # unconditional print.
        self._real_tick(self._wire(logs=[]))
        with mock.patch("builtins.print") as p:
            self.a._run_script_tick()
        out = " ".join(str(c) for c in p.call_args_list)
        self.assertNotIn("log: ", out.replace("idle:", ""))

    def test_runner_drops_are_stated(self):
        self._real_tick(self._wire(logs=["a"], logs_dropped=7))
        with mock.patch("builtins.print") as p:
            self.a._run_script_tick()
        out = " ".join(str(c) for c in p.call_args_list)
        self.assertIn("runner dropped 7 line(s)", out)

    def test_the_display_cap_reports_what_it_hid(self):
        self._real_tick(self._wire(logs=["l%d" % i for i in range(9)]))
        with mock.patch("builtins.print") as p:
            self.a._run_script_tick()
        out = " ".join(str(c) for c in p.call_args_list)
        self.assertIn("(+4 more lines this tick", out,
                      "9 lines returned, cap 5, so 4 must be reported hidden")

    def test_a_long_line_is_truncated_and_marked(self):
        self._real_tick(self._wire(logs=["x" * 500]))
        with mock.patch("builtins.print") as p:
            self.a._run_script_tick()
        out = " ".join(str(c) for c in p.call_args_list)
        self.assertIn("…", out)
        self.assertNotIn("x" * 500, out)

    def test_an_idle_tick_says_so_instead_of_returning_silently(self):
        # The core M3-1c symptom: script handled the tick, proposed nothing,
        # returned False, printed NOTHING. Eight minutes of that on test
        # produced zero [Scout/script] lines.
        self._real_tick(self._wire(actions=[]))
        with mock.patch("builtins.print") as p:
            handled = self.a._run_script_tick()
        self.assertFalse(handled)
        out = " ".join(str(c) for c in p.call_args_list)
        self.assertIn("[Scout/script] idle: no actions", out)

    def test_the_idle_line_is_rate_limited(self):
        self._real_tick(self._wire(actions=[]))
        import time as _t
        with mock.patch("builtins.print") as p:
            self.a._run_script_tick()
            self.a._run_script_tick()   # same monotonic instant: suppressed
        idle = [c for c in p.call_args_list if "idle: no actions" in str(c)]
        self.assertEqual(1, len(idle),
                         "two idle ticks inside one interval must print once")

    def test_a_stale_log_line_is_not_reprinted_as_this_ticks(self):
        # A tick that falls back must CLEAR last_logs, or the next tick that
        # reports would attribute the previous tick's lines to itself.
        st = self._real_tick(self._wire(logs=["first tick line"]))
        with mock.patch("builtins.print") as p:
            self.a._run_script_tick()
        self.assertIn("first tick line", " ".join(str(c) for c in p.call_args_list))
        # Now make the transport fail: a fallback carries no script logs.
        st._post = lambda *a, **k: {"contract_version": 1, "status": "error"}
        with mock.patch("builtins.print") as p:
            self.a._run_script_tick()
        self.assertNotIn("first tick line",
                         " ".join(str(c) for c in p.call_args_list),
                         "a fallback tick reprinted the previous tick's log line")

    def test_a_successful_bind_is_announced_once_with_the_source_digest(self):
        import hashlib
        source = "// scout body\n"
        d = tempfile.mkdtemp()
        try:
            path = os.path.join(d, "scout.js")
            with open(path, "w", encoding="utf-8") as f:
                f.write(source)
            self.a._bound_script_path = lambda: path
            self.a._script_loaded = False
            self.a._script_tick = None
            with mock.patch("builtins.print") as p:
                first = self.a._get_script_tick()
                self.a._get_script_tick()   # cache hit: must NOT print again
            expect = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
            bound = [str(c) for c in p.call_args_list if "bound " in str(c)]
            self.assertEqual(1, len(bound),
                             "the bind line must print once, not on every tick")
            self.assertIn(expect, bound[0],
                          "the announced digest must be the source's own sha16")
            self.assertIsNotNone(first)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)

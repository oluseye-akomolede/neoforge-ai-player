"""Tests for agent/script_tick.py — M2 task 3.2 wiring.

The load-bearing property is the FALLBACK (task 7.2): if anything at all goes
wrong the tick must return `handled=False` so the existing planner runs
unchanged. A regression here would leave a bot silently doing nothing, which
looks identical to a bot with nothing to do -- the failure mode this suite
exists to make visible.

The request body is pinned against the runner's real contract
(agent-script-runner src/main.js:167-216): game_id, bot_id and script_revision
are required strings, the script travels as `source`, and the snapshot goes
under `snapshot`. An earlier draft of script_tick.py invented a different body;
these tests read the runner's own source so the same drift cannot pass silently.
"""

import importlib.util
import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_RUNNER_MAIN = "/home/sigmastrain/minecraft/agent-script-runner/src/main.js"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_rc = _load("script_client_for_tick", "script_client.py")
_st = _load("script_tick_under_test", "script_tick.py")

ScriptTick = _st.ScriptTick


class _FakeApi:
    def __init__(self):
        self.posted = []

    def _post(self, path, data=None, **kw):
        self.posted.append((path, data))
        return {"contract_version": 1, "status": "ok",
                "actions": [{"kind": "MINE", "target": "iron_ore"}]}

    # readers used by snapshot.build_state
    def status(self, bot):
        return {"health": 20.0, "food": 18, "position": {"x": 0, "y": 64, "z": 0}}

    def inventory(self, bot):
        return []

    def blocks(self, bot, radius=8):
        return []

    def entities(self, bot, radius=24.0):
        return []

    def get_directive(self, bot):
        return None


def _poster(actions=None, *, state="ok"):
    """A runner transport that returns a canned contract response."""
    def _post(path, data=None, **kw):
        body = {"contract_version": 1, "status": state}
        if actions is not None:
            body["actions"] = actions
        return body
    return _post


class RequestShapeTest(unittest.TestCase):

    def test_body_matches_the_runners_contract(self):
        api = _FakeApi()
        st = ScriptTick(api, "Scout", "api.log('hi')", post=_poster(actions=[]))
        st.tick()
        path, body = api.posted[0] if api.posted else (None, None)
        # The fake api._post is not used when post is injected, so capture
        # through the injected transport instead.
        captured = {}
        def _capture(p, d=None, **kw):
            captured.update({"path": p, "data": d, "kw": kw})
            return {"contract_version": 1, "status": "ok", "actions": []}
        ScriptTick(api, "Scout", "api.log('hi')", post=_capture).tick()
        self.assertEqual(captured["path"], "/v1/tick")
        data = captured["data"]
        for field in ("game_id", "bot_id", "script_revision", "source",
                      "snapshot", "memory"):
            self.assertIn(field, data, f"runner contract requires {field}")
        self.assertIsInstance(data["game_id"], str)
        self.assertIsInstance(data["bot_id"], str)
        self.assertIsInstance(data["script_revision"], str)
        self.assertEqual(data["source"], "api.log('hi')")
        # The snapshot is nested, not flattened into the body: the runner reads
        # body.snapshot (main.js:208). It carries the contract's state fields.
        for field in ("health", "position", "inventory"):
            self.assertIn(field, data["snapshot"])

    def test_body_matches_the_runner_source_not_just_this_file(self):
        # Read the runner's handler and confirm it really destructures these
        # names. Pins the copy to the consumer, the same guard action_binding
        # uses for its vocabulary.
        if not os.path.exists(_RUNNER_MAIN):
            self.skipTest("runner source not checked out here")
        with open(_RUNNER_MAIN, encoding="utf-8") as f:
            src = f.read()
        m = re.search(r"handleTick\(body\)\s*\{\s*const \{([^}]*)\}", src)
        self.assertIsNotNone(m, "could not read handleTick's destructuring")
        required = {n.strip().split(":")[0].strip() for n in m.group(1).split(",")}
        self.assertTrue({"game_id", "bot_id", "script_revision"} <= required,
                        f"runner no longer requires these: {required}")

    def test_the_bound_is_passed_explicitly(self):
        captured = {}
        def _capture(p, d=None, **kw):
            captured["kw"] = kw
            return {"contract_version": 1, "status": "ok", "actions": []}
        ScriptTick(_FakeApi(), "Scout", "x", post=_capture).tick()
        self.assertEqual(captured["kw"].get("timeout"), _rc.SCRIPT_TIMEOUT)

    def test_revision_changes_with_the_script(self):
        a = ScriptTick(_FakeApi(), "Scout", "one")._revision
        b = ScriptTick(_FakeApi(), "Scout", "two")._revision
        c = ScriptTick(_FakeApi(), "Scout", "one")._revision
        self.assertNotEqual(a, b, "two scripts share a revision - the runner would serve stale source")
        self.assertEqual(a, c)


class FallbackTest(unittest.TestCase):
    """Every non-script outcome must hand the tick back to the planner."""

    def test_no_script_falls_through(self):
        st = ScriptTick(_FakeApi(), "Scout", "")
        self.assertFalse(st.enabled)
        handled, actions, _, detail = st.tick()
        self.assertFalse(handled)
        self.assertEqual(actions, [])

    def test_runner_down_falls_through(self):
        import requests
        def _boom(p, d=None, **kw):
            raise requests.exceptions.ConnectionError("refused")
        handled, actions, _, detail = ScriptTick(
            _FakeApi(), "Scout", "x", post=_boom).tick()
        self.assertFalse(handled)
        self.assertEqual(actions, [])

    def test_runner_silent_falls_through(self):
        import requests
        def _silent(p, d=None, **kw):
            raise requests.exceptions.ReadTimeout("no reply")
        handled, actions, _, _ = ScriptTick(
            _FakeApi(), "Scout", "x", post=_silent).tick()
        self.assertFalse(handled)
        self.assertEqual(actions, [])

    def test_runner_error_status_falls_through(self):
        handled, actions, _, detail = ScriptTick(
            _FakeApi(), "Scout", "x", post=_poster(state="error")).tick()
        self.assertFalse(handled)
        self.assertEqual(actions, [])

    def test_fallthrough_never_raises(self):
        # The caller sits in the tick loop; an exception here would kill the
        # loop rather than degrade one tick.
        for post in (_poster(state="error"), lambda p, d=None, **kw: None):
            try:
                ScriptTick(_FakeApi(), "Scout", "x", post=post).tick()
            except Exception as e:  # noqa: BLE001
                self.fail(f"tick raised {type(e).__name__}: {e}")


class BindingTest(unittest.TestCase):

    def test_bound_actions_come_back_as_directives(self):
        handled, actions, refusals, detail = ScriptTick(
            _FakeApi(), "Scout", "x",
            post=_poster(actions=[{"kind": "mine", "target": "iron_ore"}])).tick()
        self.assertTrue(handled)
        self.assertEqual(actions, [{"kind": "MINE", "target": "iron_ore"}])
        self.assertEqual(refusals, [])

    def test_script_silence_is_handled_not_passed_to_the_planner(self):
        # A script that deliberately does nothing must not have the planner
        # overrule it. This is the difference from "all actions refused".
        handled, actions, refusals, _ = ScriptTick(
            _FakeApi(), "Scout", "x", post=_poster(actions=[])).tick()
        self.assertTrue(handled)
        self.assertEqual(actions, [])

    def test_all_actions_refused_falls_back_visibly(self):
        # Every proposed action was bad. Falling through is right (the script
        # did not manage a legal action), but it must be visible, not silent.
        handled, actions, refusals, detail = ScriptTick(
            _FakeApi(), "Scout", "x",
            post=_poster(actions=[{"kind": "WORLD_EDIT"}])).tick()
        self.assertFalse(handled)
        self.assertEqual(refusals[0]["kind"], "WORLD_EDIT")

    def test_partial_refusal_runs_the_good_ones(self):
        handled, actions, refusals, _ = ScriptTick(
            _FakeApi(), "Scout", "x",
            post=_poster(actions=[{"kind": "MINE"}, {"kind": "WORLD_EDIT"}])).tick()
        self.assertTrue(handled)
        self.assertEqual(len(actions), 1)
        self.assertEqual(len(refusals), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

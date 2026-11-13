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
# The file that VALIDATES the request, which is where the contract is decided.
# This pointed at src/main.js, which holds handleTick -- the handler that runs
# only after a request was accepted. It cannot see the gate that rejects one, so
# a body missing `contract_version` passed every test here and then 409'd on
# every real tick. Read the gate, not the handler behind it.
_RUNNER_SERVER = "/home/sigmastrain/minecraft/agent-script-runner/src/server.js"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_rc = _load("script_client_for_tick", "script_client.py")
_st = _load("script_tick_under_test", "script_tick.py")

ScriptTick = _st.ScriptTick
translate_runner_actions = _st.translate_runner_actions


def _do(directive, args, *, seq):
    """One runner `api.do` record, in the shape src/binding.js actually pushes.

    Written as a helper so no test can quietly drift back to the binder's
    `{kind, ...}` shape: the record has `call` and `directive` and no `kind`.
    """
    return {"seq": seq, "call": "do", "directive": directive, "args": args}


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
        # The list this test carries is a copy of the contract, so it is only as
        # good as the copy -- the version without `contract_version` here agreed
        # with a sender that also omitted it, and both were wrong together. The
        # source-anchored test below is what keeps this list honest.
        for field in ("contract_version", "game_id", "bot_id",
                      "script_revision", "source", "snapshot", "memory"):
            self.assertIn(field, data, f"runner contract requires {field}")
        self.assertIsInstance(data["game_id"], str)
        self.assertIsInstance(data["bot_id"], str)
        self.assertIsInstance(data["script_revision"], str)
        self.assertEqual(data["source"], "api.log('hi')")
        # The snapshot is nested, not flattened into the body: the runner reads
        # body.snapshot (main.js:208). It carries the contract's state fields.
        for field in ("health", "position", "inventory"):
            self.assertIn(field, data["snapshot"])

    def test_every_field_the_runner_gates_on_is_present(self):
        # The runner's pre-routing gate, read from source. Each entry here is a
        # condition that REFUSES the request before handleTick is reached:
        #
        #   body?.contract_version !== 1   -> 409, every path
        #   body?.game_id !== tokenGame    -> 401
        #
        # A body missing any of them never reaches the handler the old version
        # of this test inspected. That is precisely how `contract_version` came
        # to be missing from a request every test called correct.
        if not os.path.exists(_RUNNER_SERVER):
            self.fail(f"runner source not at {_RUNNER_SERVER}; this test cannot "
                      "verify the contract without it")
        with open(_RUNNER_SERVER, encoding="utf-8") as f:
            src = f.read()
        gates = set(re.findall(r"body\??\.(\w+)", src))
        self.assertTrue(gates, "could not read any body.<field> gate from the runner")

        captured = {}

        def _capture(p, d=None, **kw):
            captured.update(d or {})
            return {"contract_version": 1, "status": "ok", "actions": []}

        ScriptTick(_FakeApi(), "Scout", "api.log('hi')", post=_capture).tick()
        missing = sorted(f for f in gates if f not in captured)
        self.assertEqual(missing, [],
                         f"runner gates on {sorted(gates)} but the tick body "
                         f"omits {missing}; every such tick is refused before "
                         "it is handled")

    def test_the_body_sends_contract_version_one(self):
        # Called out separately because it is the field that was missing and
        # because the value matters, not just its presence: the runner refuses
        # anything that is not exactly 1.
        captured = {}

        def _capture(p, d=None, **kw):
            captured.update(d or {})
            return {"contract_version": 1, "status": "ok", "actions": []}

        ScriptTick(_FakeApi(), "Scout", "api.log('hi')", post=_capture).tick()
        self.assertEqual(captured.get("contract_version"), 1)

    def test_the_bound_is_passed_explicitly(self):
        captured = {}
        def _capture(p, d=None, **kw):
            captured["kw"] = kw
            return {"contract_version": 1, "status": "ok", "actions": []}
        ScriptTick(_FakeApi(), "Scout", "x", post=_capture).tick()
        self.assertEqual(captured["kw"].get("timeout"), _rc.SCRIPT_TIMEOUT)

    def test_no_runner_url_falls_through_instead_of_posting_to_the_mod(self):
        # The defect this exists to catch: the transport defaulted to
        # `api._post`, which prefixes MOD_API_URL. A ScriptTick built the way
        # agent.py builds it (post=None) therefore POSTed script ticks to the
        # GAME MOD. The mod answers JSON, so call_runner would read it as a
        # script result or a fallback -- silently, with the tick never reaching
        # the runner. Nothing in the agent read a runner URL at all.
        posted = []

        class _Api:
            def _post(self, path, data=None, timeout=5):
                posted.append(path)
                return {"contract_version": 1, "status": "ok", "actions": []}

        import config
        original = config.SCRIPT_RUNNER_URL
        config.SCRIPT_RUNNER_URL = ""
        try:
            handled, actions, refusals, detail = ScriptTick(
                _Api(), "Scout", "x").tick()
        finally:
            config.SCRIPT_RUNNER_URL = original

        self.assertFalse(handled, "no runner configured must fall through to the planner")
        self.assertEqual(posted, [], "posted a tick with no runner URL - to the mod?")
        self.assertIn("SCRIPT_RUNNER_URL", detail)

    def test_transport_posts_to_the_runner_not_the_mod(self):
        seen = {}

        import script_tick
        import config
        original_url = config.SCRIPT_RUNNER_URL
        original_token = config.RUNNER_TOKEN
        config.SCRIPT_RUNNER_URL = "http://runner.example:8080/"
        # A token too, because a transport without one is deliberately None now:
        # the runner 401s every unauthenticated call, so a transport that would
        # always be refused is misconfiguration, not a runner.
        config.RUNNER_TOKEN = "test-token-not-real"
        try:
            transport = script_tick._default_transport()
        finally:
            config.SCRIPT_RUNNER_URL = original_url
            config.RUNNER_TOKEN = original_token
        self.assertIsNotNone(transport)
        # Bound the URL it will hit rather than trusting the string.
        seen["src"] = __import__("inspect").getsource(script_tick._default_transport)
        self.assertIn("SCRIPT_RUNNER_URL", seen["src"])
        self.assertNotIn("MOD_API_URL", seen["src"],
                         "_default_transport must not reach for the mod's URL")

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
        # The fixture is the RUNNER's record -- `{seq, call, directive, args}`
        # -- not the binder's `{kind, ...}`. Feeding the binder's shape here is
        # what let every action be refused in production while these tests
        # stayed green: the fixture agreed with the consumer, and nothing in
        # the suite held the producer's side of the contract.
        handled, actions, refusals, detail = ScriptTick(
            _FakeApi(), "Scout", "x",
            post=_poster(actions=[_do("MINE", {"target": "iron_ore"},
                                      seq=1)])).tick()
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
            post=_poster(actions=[_do("WORLD_EDIT", {}, seq=1)])).tick()
        self.assertFalse(handled)
        self.assertEqual(len(refusals), 1)
        self.assertIn("WORLD_EDIT", refusals[0]["error"])
        self.assertEqual(refusals[0]["seq"], 1)

    def test_partial_refusal_runs_the_good_ones(self):
        handled, actions, refusals, _ = ScriptTick(
            _FakeApi(), "Scout", "x",
            post=_poster(actions=[_do("MINE", {"target": "stone"}, seq=1),
                                  _do("WORLD_EDIT", {}, seq=2)])).tick()
        self.assertTrue(handled)
        self.assertEqual(actions, [{"kind": "MINE", "target": "stone"}])
        self.assertEqual(len(refusals), 1)
        self.assertEqual(refusals[0]["seq"], 2)


class RunnerRecordTranslationTest(unittest.TestCase):
    """The boundary where the runner's record meets the binder's input.

    Every case here uses the record the runner actually emits
    (agent-script-runner src/binding.js pushes `{seq, call, directive, args}`),
    never a hand-written binder-shaped fixture.
    """

    def test_a_do_record_becomes_kind_plus_flat_args(self):
        pairs, refusals = translate_runner_actions(
            [_do("STORE_ALL", {}, seq=7)])
        self.assertEqual(refusals, [])
        self.assertEqual(pairs, [({"kind": "STORE_ALL"}, 7)])

    def test_null_args_are_treated_as_no_arguments(self):
        # binding.js writes `null` for undefined args so the field always
        # exists; it means "no arguments", not "arguments are broken".
        pairs, refusals = translate_runner_actions(
            [{"seq": 3, "call": "do", "directive": "STORE_ALL", "args": None}])
        self.assertEqual(refusals, [])
        self.assertEqual(pairs, [({"kind": "STORE_ALL"}, 3)])

    def test_a_say_record_is_refused_by_name_not_as_a_missing_kind(self):
        # say/send shares the same actions list. Refusing it as "no 'kind'"
        # would send a script author looking for a bug that is not there.
        pairs, refusals = translate_runner_actions(
            [{"seq": 4, "call": "say", "text": "hi"}])
        self.assertEqual(pairs, [])
        self.assertIn("say", refusals[0]["error"])
        self.assertEqual(refusals[0]["seq"], 4)

    def test_a_send_record_is_refused_by_name(self):
        pairs, refusals = translate_runner_actions(
            [{"seq": 5, "call": "send", "to": "S1", "msg": "x"}])
        self.assertEqual(pairs, [])
        self.assertIn("send", refusals[0]["error"])

    def test_a_missing_directive_is_refused_with_its_seq(self):
        pairs, refusals = translate_runner_actions([{"seq": 6, "call": "do"}])
        self.assertEqual(pairs, [])
        self.assertEqual(refusals[0]["seq"], 6)
        self.assertIn("directive", refusals[0]["error"])

    def test_a_non_string_directive_is_refused(self):
        pairs, refusals = translate_runner_actions(
            [{"seq": 8, "call": "do", "directive": 42, "args": {}}])
        self.assertEqual(pairs, [])
        self.assertEqual(refusals[0]["seq"], 8)

    def test_non_object_args_are_refused_not_coerced(self):
        pairs, refusals = translate_runner_actions(
            [_do("STORE_ALL", ["not", "a", "dict"], seq=9)])
        self.assertEqual(pairs, [])
        self.assertEqual(refusals[0]["seq"], 9)
        self.assertIn("args", refusals[0]["error"])

    def test_args_named_kind_or_action_are_refused(self):
        # bind_action reads kind/action as the action name, so an arg by that
        # name would silently become the directive and the real one lost.
        for reserved in ("kind", "action"):
            pairs, refusals = translate_runner_actions(
                [_do("MINE", {reserved: "WORLD_EDIT"}, seq=10)])
            self.assertEqual(pairs, [], reserved)
            self.assertEqual(len(refusals), 1, reserved)
            self.assertIn(reserved, refusals[0]["error"])

    def test_one_bad_record_does_not_suppress_the_others(self):
        pairs, refusals = translate_runner_actions(
            [_do("STORE_ALL", {}, seq=1),
             {"seq": 2, "call": "say", "text": "hi"},
             _do("MINE", {"target": "stone"}, seq=3)])
        self.assertEqual([p[1] for p in pairs], [1, 3])
        self.assertEqual([r["seq"] for r in refusals], [2])

    def test_the_seq_survives_to_the_bound_actions_in_order(self):
        _h, actions, refusals, _d = ScriptTick(
            _FakeApi(), "Scout", "x",
            post=_poster(actions=[_do("MINE", {"target": "a"}, seq=11),
                                  _do("MINE", {"target": "b"}, seq=12),
                                  _do("MINE", {"target": "c"}, seq=13)])).tick()
        self.assertEqual(refusals, [])
        self.assertEqual(len(actions), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)

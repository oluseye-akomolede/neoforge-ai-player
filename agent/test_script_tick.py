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

import base64
import importlib.util
import json as _json
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


def _poster(actions=None, *, state="ok", result=None):
    """A runner transport that returns a canned contract response.

    `result` is the `{text, truncated}` the runner carries when a script
    called api.result. It is sent on the error branch too (runner
    src/main.js:255), which is the case a thrown tick's report travels on.
    """
    def _post(path, data=None, **kw):
        body = {"contract_version": 1, "status": state}
        if actions is not None:
            body["actions"] = actions
        if result is not None:
            body["result"] = result
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
        # body.snapshot (main.js:208). The contract's state fields live under
        # `snapshot.state` -- the envelope that `build_envelope` produces and
        # that every script reads as `snapshot.state.<field>`. Asserting them
        # at `snapshot` top level, as this did until M3-1c part 5, pinned the
        # bare-state shape that made every script field undefined in production.
        self.assertIn("state", data["snapshot"],
                      "snapshot must be the envelope, with bot facts under "
                      "'state'")
        for field in ("health", "position", "inventory"):
            self.assertIn(field, data["snapshot"]["state"])

    def test_dry_flag_reaches_the_runner_body(self):
        # M3-2 step (a): the runner's dry mode is only reachable if the agent
        # SENDS the flag. The rate window lives inside the runner process, so
        # the agent cannot protect it by anything it does locally; the request
        # body is the whole mechanism.
        #
        # KILLS: a _dry_tick that runs the normal tick without asking the
        # runner for dry. That script spends the bot's real do/say/log slots
        # (30/30 per minute), and nothing in the agent can see it happen.
        captured = {}
        def _capture(p, d=None, **kw):
            captured.update({"path": p, "data": d})
            return {"contract_version": 1, "status": "ok", "actions": []}
        ScriptTick(_FakeApi(), "Scout", "api.log('hi')",
                   post=_capture, dry=True).tick()
        self.assertIn("dry", captured["data"],
                      "the runner cannot run dry if the body never says so")
        self.assertIs(captured["data"]["dry"], True,
                      "dry must be the boolean true; the runner tests `=== true`")

    def test_dry_flag_is_absent_unless_asked(self):
        # The flag must be additive: every existing caller -- the live tick
        # path, and cardgame's own caller -- keeps today's body byte for byte.
        # KILLS: a default of `dry: True` (every tick dry, nothing ever
        # dispatches) or `dry: False` (a field the runner did not receive
        # before, risking a strict validator). Absent is what "unchanged"
        # means.
        captured = {}
        def _capture(p, d=None, **kw):
            captured.update({"path": p, "data": d})
            return {"contract_version": 1, "status": "ok", "actions": []}
        ScriptTick(_FakeApi(), "Scout", "api.log('hi')", post=_capture).tick()
        self.assertNotIn("dry", captured["data"],
                         "a live tick must send exactly the body it sent before")

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

    def test_a_failed_tick_that_reported_holds_its_result_as_failure(self):
        # This test used to assert only `handled` and `actions`, so the whole
        # carried-result path was dead while it passed (reviewer, 05:26Z). The
        # runner sends `result` on the error branch; the agent must keep it,
        # and must keep it as a FAILURE -- the throw happened before the
        # script could set `done`, so the carried report has no verdict and a
        # no-verdict result is read as `done` downstream.
        #
        # KILLS: dropping the result on any non-script state (the old code),
        # and holding it with no classification (which the trigger mapper
        # turns into `done`).
        #
        # `error: True` is asserted, not incidental: it is what distinguishes
        # this throw from a script that returns `{done: false}` and is still
        # WORKING. Both carry `ok: False`, so without it the caller cannot
        # tell a failure from a wait and either unbinds a live script or
        # reports a dead one as pending (0eea399).
        st = ScriptTick(_FakeApi(), "Scout", "x",
                        post=_poster(state="error", result={
                            "text": "partial scan, 3 blocks", "truncated": False}))
        handled, actions, _, _ = st.tick()
        self.assertFalse(handled,
                         "a failed tick must still fall back to the planner")
        self.assertEqual(actions, [],
                         "a failed tick's actions are not trusted")
        self.assertEqual(
            st.last_result,
            {"text": "partial scan, 3 blocks", "truncated": False,
             "ok": False, "error": True},
            "the result a throwing tick carried must be held, as a FAILURE "
            "(`error: True`), not merely as `ok: False` -- a no-verdict "
            "result is read as `done` downstream")

    def test_a_failed_tick_with_no_result_holds_nothing(self):
        # The control: a bare error (a timeout, a refusal) carries no result,
        # so nothing must be invented for it.
        st = ScriptTick(_FakeApi(), "Scout", "x", post=_poster(state="error"))
        st.tick()
        self.assertIsNone(st.last_result,
                          "a failed tick that reported nothing must hold "
                          "nothing")

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
        pairs, refusals, _deliveries = translate_runner_actions(
            [_do("STORE_ALL", {}, seq=7)])
        self.assertEqual(refusals, [])
        self.assertEqual(pairs, [({"kind": "STORE_ALL"}, 7)])

    def test_null_args_are_treated_as_no_arguments(self):
        # binding.js writes `null` for undefined args so the field always
        # exists; it means "no arguments", not "arguments are broken".
        pairs, refusals, _deliveries = translate_runner_actions(
            [{"seq": 3, "call": "do", "directive": "STORE_ALL", "args": None}])
        self.assertEqual(refusals, [])
        self.assertEqual(pairs, [({"kind": "STORE_ALL"}, 3)])

    def test_a_say_record_is_routed_to_delivery_not_refused(self):
        # say/send share the same actions list as do. Until 2026-11-20 22:21Z
        # they were refused here, so a script that chatted every minute never
        # spoke in game. They are now routed out of binding and delivered.
        # KILLS: restoring the refusal that made the say-only trial silent.
        pairs, refusals, deliveries = translate_runner_actions(
            [{"seq": 4, "call": "say", "text": "hi"}])
        self.assertEqual(pairs, [])
        self.assertEqual(refusals, [])
        self.assertEqual([d["seq"] for d in deliveries], [4])

    def test_tick_exposes_the_routed_deliveries_to_its_caller(self):
        # The routing is worthless if tick() does not hand the deliveries to
        # the caller: agent.py delivers whatever `last_deliveries` holds, so a
        # tick that parses them and then drops them is silent in game exactly
        # like the refusal it replaced.
        # KILLS: self.last_deliveries = [] (parsed and discarded).
        st = ScriptTick(
            _FakeApi(), "Scout", "x",
            post=_poster(actions=[{"seq": 2, "call": "say", "text": "hi"},
                                  {"seq": 3, "call": "send", "to": "S1", "msg": "yo"}]))
        handled, actions, refusals, _detail = st.tick()
        self.assertTrue(handled)
        self.assertEqual(actions, [])
        self.assertEqual(refusals, [])
        self.assertEqual([d["seq"] for d in st.last_deliveries], [2, 3])

    def test_a_send_record_is_routed_to_delivery_not_refused(self):
        pairs, refusals, deliveries = translate_runner_actions(
            [{"seq": 5, "call": "send", "to": "S1", "msg": "x"}])
        self.assertEqual(pairs, [])
        self.assertEqual(refusals, [])
        self.assertEqual([d["seq"] for d in deliveries], [5])

    def test_an_unknown_call_kind_is_still_refused_by_name(self):
        """Routing say/send out must not turn into accepting ANY non-do call.
        KILLS: routing by `call != 'do'`, which would deliver 'teleport'."""
        pairs, refusals, deliveries = translate_runner_actions(
            [{"seq": 7, "call": "teleport", "x": 1}])
        self.assertEqual(pairs, [])
        self.assertEqual(deliveries, [])
        self.assertIn("teleport", refusals[0]["error"])
        self.assertEqual(refusals[0]["seq"], 7)

    def test_a_missing_directive_is_refused_with_its_seq(self):
        pairs, refusals, _deliveries = translate_runner_actions([{"seq": 6, "call": "do"}])
        self.assertEqual(pairs, [])
        self.assertEqual(refusals[0]["seq"], 6)
        self.assertIn("directive", refusals[0]["error"])

    def test_a_non_string_directive_is_refused(self):
        pairs, refusals, _deliveries = translate_runner_actions(
            [{"seq": 8, "call": "do", "directive": 42, "args": {}}])
        self.assertEqual(pairs, [])
        self.assertEqual(refusals[0]["seq"], 8)

    def test_non_object_args_are_refused_not_coerced(self):
        pairs, refusals, _deliveries = translate_runner_actions(
            [_do("STORE_ALL", ["not", "a", "dict"], seq=9)])
        self.assertEqual(pairs, [])
        self.assertEqual(refusals[0]["seq"], 9)
        self.assertIn("args", refusals[0]["error"])

    def test_args_named_kind_or_action_are_refused(self):
        # bind_action reads kind/action as the action name, so an arg by that
        # name would silently become the directive and the real one lost.
        for reserved in ("kind", "action"):
            pairs, refusals, _deliveries = translate_runner_actions(
                [_do("MINE", {reserved: "WORLD_EDIT"}, seq=10)])
            self.assertEqual(pairs, [], reserved)
            self.assertEqual(len(refusals), 1, reserved)
            self.assertIn(reserved, refusals[0]["error"])

    def test_one_bad_record_does_not_suppress_the_others(self):
        pairs, refusals, deliveries = translate_runner_actions(
            [_do("STORE_ALL", {}, seq=1),
             {"seq": 2, "call": "teleport"},
             _do("MINE", {"target": "stone"}, seq=3)])
        self.assertEqual([p[1] for p in pairs], [1, 3])
        self.assertEqual([r["seq"] for r in refusals], [2])
        self.assertEqual(deliveries, [])

    def test_the_seq_survives_to_the_bound_actions_in_order(self):
        st = ScriptTick(
            _FakeApi(), "Scout", "x",
            post=_poster(actions=[_do("MINE", {"target": "a"}, seq=11),
                                  _do("MINE", {"target": "b"}, seq=12),
                                  _do("MINE", {"target": "c"}, seq=13)]))
        _h, actions, refusals, _d = st.tick()
        self.assertEqual(refusals, [])
        self.assertEqual([a["kind"] for a in actions], ["MINE"] * 3)
        self.assertEqual(st._last_action_seqs, [11, 12, 13])

    def test_seqs_stay_with_their_actions_when_a_middle_one_is_refused(self):
        # The alignment is index-based against bind_actions' output, which is
        # only sound if bound actions come back in input order. This is the
        # case that would expose a slide: record 1 binds, record 2 is refused
        # by the BINDER (unknown kind), record 3 binds. If the seq list were
        # built from position-in-bound rather than position-in-pairs, record 3
        # would be reported as seq 12.
        st = ScriptTick(
            _FakeApi(), "Scout", "x",
            post=_poster(actions=[_do("MINE", {"target": "a"}, seq=11),
                                  _do("WORLD_EDIT", {}, seq=12),
                                  _do("DROP", {"target": "stone"}, seq=13)]))
        _h, actions, refusals, _d = st.tick()
        self.assertEqual([a["kind"] for a in actions], ["MINE", "DROP"])
        self.assertEqual(st._last_action_seqs, [11, 13])
        self.assertEqual([r["seq"] for r in refusals], [12])

    def test_a_say_between_two_dos_does_not_shift_the_bind_seqs(self):
        # A say consumes a seq in the runner and never becomes a directive, so
        # the seqs for the bound actions must still be 11 and 13, not 11 and
        # 12. This is why the pairs carry their own seq rather than being
        # zipped against a list of seqs by position.
        #
        # The say is now ROUTED to delivery rather than refused, so the gap it
        # leaves is the point: it is still not in `_last_action_seqs`.
        st = ScriptTick(
            _FakeApi(), "Scout", "x",
            post=_poster(actions=[_do("MINE", {"target": "a"}, seq=11),
                                  {"seq": 12, "call": "say", "text": "hi"},
                                  _do("DROP", {"target": "stone"}, seq=13)]))
        _h, actions, refusals, _d = st.tick()
        self.assertEqual([a["kind"] for a in actions], ["MINE", "DROP"])
        self.assertEqual(st._last_action_seqs, [11, 13])
        self.assertEqual(refusals, [])
        self.assertEqual([d["seq"] for d in st.last_deliveries], [12])


class MemoryRoundTripTest(unittest.TestCase):
    """M3-1b cause A: the agent must CARRY the script's memory between ticks.

    The bug this pins was invisible to every existing test because each one
    hand-fed `memory_out` back into the next request. Production has no such
    hand: `ScriptTick` was constructed without `memory=` and nothing read
    `result.memory`, so `api.recall()` returned null on every real tick and the
    STORE_ALL cooldown could never engage. These tests drive two ticks through
    one `ScriptTick` and read what the SECOND request carried.
    """

    def _two_ticks(self, memory_out):
        """Drive two ticks through one ScriptTick; return the second request."""
        bodies = []
        def _post(path, data=None, **kw):
            bodies.append(data)
            return {"contract_version": 1, "status": "ok", "actions": [],
                    "memory_out": memory_out}
        api = _FakeApi()
        st = ScriptTick(api, "Scout", "api.log('hi')", post=_post)
        st.tick()
        st.tick()
        return bodies[0], bodies[1]

    def test_the_first_tick_sends_no_memory(self):
        first, _ = self._two_ticks("c2NvdXQ=")
        self.assertIsNone(first["memory"],
                          "a fresh agent has nothing remembered to send")

    def test_memory_out_from_tick_one_is_sent_on_tick_two(self):
        _, second = self._two_ticks("c2NvdXQ=")
        self.assertEqual(second["memory"], "c2NvdXQ=",
                         "memory_out must be carried verbatim to the next tick; "
                         "the runner returns it base64 and decodes it on "
                         "arrival (engine.js:1059), so re-encoding double-codes")

    def test_a_fallback_tick_does_not_wipe_remembered_memory(self):
        """A runner timeout carries memory=None; taking it would lose the blob."""
        bodies = []
        results = [
            {"contract_version": 1, "status": "ok", "actions": [],
             "memory_out": "c2NvdXQ="},
            {"contract_version": 1, "status": "timeout", "detail": "slow"},
        ]
        def _post(path, data=None, **kw):
            bodies.append(data)
            return results.pop(0)
        st = ScriptTick(_FakeApi(), "Scout", "api.log('hi')", post=_post)
        st.tick()
        st.tick()
        self.assertEqual(bodies[1]["memory"], "c2NvdXQ=",
                         "a timeout must not erase what was already remembered")

    def test_constructor_memory_is_encoded_for_the_wire(self):
        captured = {}
        def _post(path, data=None, **kw):
            captured.update(data)
            return {"contract_version": 1, "status": "ok", "actions": []}
        st = ScriptTick(_FakeApi(), "Scout", "api.log('hi')", post=_post,
                        memory='{"lastStoreAllTick": 7}')
        st.tick()
        self.assertEqual(base64.b64decode(captured["memory"]).decode("utf-8"),
                         '{"lastStoreAllTick": 7}',
                         "a plain string from the caller must be encoded once")

    def test_a_successful_tick_that_does_not_remember_keeps_the_blob(self):
        """M3-1e bug 1: a SCRIPT tick with memory_out null must not erase memory.

        Measured on test 2026-11-19 (image m31d-a995779): STORE_ALL dispatched
        every 2 ticks for 8 minutes. The cause is here, not in the script. The
        runner sets `memoryOut` ONLY when the script calls `api.remember`
        (binding.js:314) and resets it to null every tick (binding.js:113), so
        a tick that logs and returns without storing carries `memory_out: null`.
        Assigning that to `self._memory` wiped the cooldown stamp on every
        non-storing tick, so the next tick saw `lastStoreAllTick` absent and
        stored again -- a store, a cool, a store, a cool, forever.

        `None` from a fallback means "the call did not happen"; null on a
        SCRIPT tick means "the script chose not to write". They are different,
        and only the first may clear the blob.
        """
        bodies = []
        results = [
            # tick 1: the script stored and remembered the tick stamp
            {"contract_version": 1, "status": "ok",
             "actions": [{"seq": 1, "call": "do", "directive": "STORE_ALL"}],
             "memory_out": "eyJsYXN0U3RvcmVBbGxUaWNrIjoyfQ=="},
            # tick 2: it held the cooldown and never called remember
            {"contract_version": 1, "status": "ok", "actions": [],
             "memory_out": None},
            # tick 3: should still be cooling
            {"contract_version": 1, "status": "ok", "actions": [],
             "memory_out": None},
        ]
        def _post(path, data=None, **kw):
            bodies.append(data)
            return results.pop(0)
        st = ScriptTick(_FakeApi(), "Scout", "api.log('hi')", post=_post)
        st.tick(); st.tick(); st.tick()
        self.assertEqual(bodies[1]["memory"], "eyJsYXN0U3RvcmVBbGxUaWNrIjoyfQ==",
                         "a non-storing SCRIPT tick must carry the previous blob")
        self.assertEqual(bodies[2]["memory"], "eyJsYXN0U3RvcmVBbGxUaWNrIjoyfQ==",
                         "and the one after it, for as long as the script stays quiet")


class SnapshotWireShapeTest(unittest.TestCase):
    """M3-1c part 5: `snapshot` on the wire must be the ENVELOPE.

    The script reads `snapshot.state.<field>` (scout.js:65) because
    `build_envelope` wraps the bot facts under a `state` key. Production builds
    `ScriptTick` with no cache (agent.py:2881), so `_build_snapshot` falls to
    `snapshot_mod.build_state`, which returns `(state, errors)` -- the STATE,
    not an envelope. Unpacked as `envelope, snap_errors`, that put a bare state
    object on the wire with no `state` key, so every `snapshot.state.*` read in
    the script returned undefined. Measured on TEST 2026-11-19: Scout logged
    "inventory empty" every tick while holding 16 cobblestone.

    Every existing test missed it because each one either injected a cache or
    stubbed the snapshot; none drove the no-cache path the agent actually uses.
    """

    def _captured_snapshot(self):
        captured = {}

        def _post(path, data=None, **kw):
            captured.update(data)
            return {"contract_version": 1, "status": "ok", "actions": []}

        class _Api(_FakeApi):
            def inventory(self, bot):
                # The mod's real shape (HttpApiServer.java:469): a wrapper.
                return {"inventory": [
                    {"slot": 0, "item": "minecraft:cobblestone", "count": 16},
                ]}

        st = ScriptTick(_Api(), "Scout", "api.log('hi')", post=_post)
        st.tick()
        return captured["snapshot"]

    def test_snapshot_on_the_wire_is_the_envelope(self):
        snap = self._captured_snapshot()
        self.assertIn("state", snap,
                      "the wire snapshot must be the envelope; a bare state "
                      "object makes every snapshot.state.* read undefined")
        self.assertIn("tick", snap)
        self.assertIn("task", snap)

    def test_the_scripts_inventory_path_resolves(self):
        # The path scout.js reads is snapshot.state.inventory, and it is a LIST.
        # This assertion used to pin `state.inventory.inventory` instead, i.e.
        # it encoded the bug rather than the contract: it passed for as long as
        # build_state stored the game's wrapper, and went red the moment the
        # wrapper was unwrapped at the source - which is the correct direction
        # for it to fail. Assert the contract, then assert the script agrees.
        snap = self._captured_snapshot()
        inv = (snap.get("state") or {}).get("inventory")
        self.assertIsInstance(
            inv, list,
            "snapshot.state.inventory must be a list (snapshot.py _EMPTY_STATE); "
            "a wrapped dict here is what makes scout's guard never fire")
        self.assertEqual(1, len(inv),
                         "it must hold the bot's items")
        self.assertEqual("minecraft:cobblestone", inv[0]["item"])

    def test_the_scout_script_reads_the_inventory_list_the_snapshot_sends(self):
        # test_the_scripts_inventory_path_resolves pins the WIRE shape; this one
        # pins that the script actually reads it, so the two cannot drift apart
        # again with both suites green.
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "scripts", "scout.js"), encoding="utf-8") as fh:
            src = fh.read()
        code = "\n".join(line.split("//")[0] for line in src.splitlines())
        self.assertNotIn(
            "inventory.inventory", code,
            "scout.js reads state.inventory.inventory; state.inventory is a "
            "list, so that guard never fires and the bot never stores")

    def test_health_is_readable_where_the_script_reads_it(self):
        snap = self._captured_snapshot()
        self.assertEqual(20.0, (snap.get("state") or {}).get("health"),
                         "the health guard reads snapshot.state.health; it was "
                         "undefined on every tick for the same reason")

    def test_a_cached_tick_and_an_uncached_tick_agree(self):
        uncached = self._captured_snapshot()

        captured = {}
        def _post(path, data=None, **kw):
            captured.update(data)
            return {"contract_version": 1, "status": "ok", "actions": []}

        class _Api(_FakeApi):
            def inventory(self, bot):
                return {"inventory": [{"slot": 0, "item": "minecraft:cobblestone",
                                       "count": 16}]}

        cache = _st.snapshot_mod.SnapshotCache(_Api(), ttl=60)
        st = ScriptTick(_Api(), "Scout", "api.log('hi')", post=_post, cache=cache)
        st.tick()
        cached = captured["snapshot"]
        # Both paths must produce the same top-level shape, or a bot behaves
        # differently depending on how its ScriptTick happened to be built.
        self.assertEqual(sorted(uncached.keys()), sorted(cached.keys()),
                         "cached and uncached ticks must send the same shape")


class TestAScriptReportIsCappedButKept(unittest.TestCase):
    """Design §3, task 3.2.

    A report larger than the cap is cut and MARKED, not dropped. The planner
    must be able to tell a cut report from a complete one, because a partial
    report read as complete is worse than no report at all.
    """

    def test_a_small_report_passes_through_unchanged(self):
        # KILLS: an implementation that always truncates, or that re-serialises
        # with a different shape than the script handed over.
        text, truncated = _st.cap_result({"colour": "red", "n": 2})
        self.assertFalse(truncated)
        self.assertEqual(_json.loads(text), {"colour": "red", "n": 2})

    def test_a_report_over_the_cap_is_marked_not_dropped(self):
        # KILLS: the version that MAKES THE PLANNER BE LIE says it must drop a
        # too-large result entirely; the design says keep it, capped and marked.
        # A dropped result is indistinguishable from a script that reported
        # nothing, which is a different fact.
        big = "x" * (_st.RESULT_CAP_BYTES * 4)
        text, truncated = _st.cap_result({"note": big})
        self.assertTrue(truncated, "an oversized report must report truncated=True")
        self.assertIsNotNone(text, "an oversized report must not be dropped")
        self.assertTrue(text.endswith(_st.RESULT_TRUNCATED_MARKER),
                        "a cut report must carry the marker, or it reads as complete")

    def test_the_cut_report_is_still_valid_text(self):
        # KILLS: a byte-slice cut emitted mid-UTF-8-character, i.e. a report
        # whose bytes are not valid UTF-8 -- which is what a consumer further
        # down the line chokes on. MUTANT: replace the decode with
        # decode("latin-1"), which accepts the byte cut and emits a string whose
        # bytes differ from the original.
        #
        # The check is on the BYTES, not the str: text.encode('utf-8') always
        # round-trips, so asserting on the round-trip tests nothing. What must
        # hold is that the cut is a prefix of the true serialisation and is
        # itself valid UTF-8.
        value = {"note": "€" * 2000}
        raw = _json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        text, truncated = _st.cap_result(value)
        self.assertTrue(truncated)
        body = text[: -len(_st.RESULT_TRUNCATED_MARKER)]
        got = body.encode("utf-8")
        self.assertTrue(raw.startswith(got),
                        "the cut must be a byte prefix of the real serialisation,"
                        " not a reinterpretation of its bytes")
        got.decode("utf-8")  # and those bytes must be decodable as UTF-8

    def test_the_cap_counts_bytes_not_characters(self):
        # KILLS: len(text) instead of len(text.encode('utf-8')). A 2 KiB cap is a
        # cap on what crosses the wire; for non-ASCII text the character count
        # is smaller than the byte count, so char-counting overruns.
        # 1500 three-byte characters is 1500 chars but 4500 bytes.
        text, truncated = _st.cap_result({"note": "€" * 1500})
        self.assertTrue(truncated,
                        "4500 bytes of non-ASCII must exceed a 2048-BYTE cap")

    def test_no_report_is_its_own_case_not_an_empty_one(self):
        # KILLS: returning ('null', False) for None, which makes "the script
        # reported nothing" indistinguishable from "the script reported null".
        text, truncated = _st.cap_result(None)
        self.assertIsNone(text)
        self.assertFalse(truncated)

    def test_an_unserialisable_report_is_absent_not_a_repr(self):
        # KILLS: falling back to repr(value). A repr of an unserialisable object
        # is not what the script meant to report, and passing it on invents a
        # result the script never produced.
        text, truncated = _st.cap_result({"o": object()})
        self.assertIsNone(text)
        self.assertFalse(truncated)


class TestTheTickHoldsWhatTheScriptReported(unittest.TestCase):
    """`last_result` is what the script handed over, kept for the planner.

    The runner sends the report ALREADY serialised. Everything here is about
    the tick not damaging that text on its way through.
    """

    def _tick_with(self, reported):
        tick = _st.ScriptTick.__new__(_st.ScriptTick)
        tick.last_result = None
        result = _rc.ScriptResult("script", result=reported)
        tick._hold_result(result)
        return tick.last_result

    def test_a_report_is_kept_verbatim(self):
        # The planner reads this text. Re-serialising it would quote it.
        # KILLS: cap_result(result.result) -- passing the dict instead of
        # text= serialises the string a second time, so the planner sees
        # "\"{\\\"found\\\":\\\"oak\\\"}\"" instead of the report.
        self.assertEqual(self._tick_with({"text": '{"found":"oak"}',
                                          "truncated": False}),
                         {"text": '{"found":"oak"}', "truncated": False,
                          "ok": None})

    def test_no_report_holds_none(self):
        # KILLS: initialising last_result to {} -- an empty report is not the
        # same as no report, and the planner would read it as "nothing found".
        self.assertIsNone(self._tick_with(None))

    def test_an_oversize_report_is_cut_and_marked(self):
        # The runner should have capped this. If it did not, the tick must
        # not hand 4 KiB of text to a planner that budgets 2 KiB.
        # KILLS: trusting the runner's cap -- removing the re-cut leaves 4096
        # bytes in last_result.
        big = "x" * 4096
        held = self._tick_with({"text": big, "truncated": False})
        self.assertLessEqual(len(held["text"].encode("utf-8")), _st.RESULT_CAP_BYTES)
        self.assertTrue(held["truncated"])

    def test_the_runners_truncation_flag_is_kept(self):
        # The runner may have capped a report that is short by the time it
        # lands?  It cannot -- but the flag must survive regardless, because a
        # re-cut that clears it would report a partial result as complete.
        # KILLS: last_result = {"text": ..., "truncated": cut} -- dropping the
        # runner's flag makes a truncated report read as whole.
        held = self._tick_with({"text": "abc", "truncated": True})
        self.assertTrue(held["truncated"])


class TestTheScriptsOwnVerdict(unittest.TestCase):
    """Whether a result says the work SUCCEEDED, from the script's `done` field.

    Every result used to be stored as trigger "done" whatever it said, so a
    script returning `{done: false, reason: "no diamond_ore within 32 blocks"}`
    CLOSED its goal as done -- the goal then never re-planned (lead report,
    05:15Z). The classifier is the structured flag, never the prose.
    """

    def test_done_false_is_a_failure(self):
        # The reported shape. KILLS: treating any result as done -- the goal
        # closes and the bot stops with the work unfinished.
        self.assertIs(_st.result_verdict('{"done": false, "reason": "none"}'),
                      False)

    def test_done_true_is_success(self):
        self.assertIs(_st.result_verdict('{"done": true, "found": 3}'), True)

    def test_the_word_failed_alone_is_not_a_verdict(self):
        # The lead's Forge script reported the STRING "Failed: no diamond_ore
        # found". Matching prose would make a script unable to use the word in
        # a success message, and unable to report failure without it. A
        # string is no verdict.
        self.assertIsNone(_st.result_verdict(
            "Failed: no diamond_ore found within 32 blocks"))

    def test_a_success_message_may_contain_the_word_failed(self):
        # The converse must hold, or the flag is not a flag.
        self.assertIs(_st.result_verdict(
            '{"done": true, "note": "first attempt failed, retried"}'), True)

    def test_a_non_boolean_done_is_no_verdict(self):
        # "false" the STRING is truthy in some languages and false in others.
        # Guessing here would silently invert a result, so it is not a verdict.
        for text in ('{"done": "false"}', '{"done": 0}', '{"done": null}'):
            self.assertIsNone(_st.result_verdict(text), text)

    def test_a_json_value_that_is_not_an_object_is_no_verdict(self):
        for text in ("[1,2]", "42", '"done"', "null", ""):
            self.assertIsNone(_st.result_verdict(text), text)

    def test_undecodable_text_is_no_verdict_not_an_error(self):
        # A truncated result is re-cut mid-JSON by design (the cap), so the
        # common case is unparseable text. It must not raise.
        self.assertIsNone(_st.result_verdict('{"done": tr... [truncated]'))
        self.assertIsNone(_st.result_verdict(None))

    def test_the_held_result_carries_the_verdict(self):
        # The seam agent.py reads (`result.get("ok")`). KILLS: dropping the
        # "ok" key from _hold_result -- the trigger is then None forever and
        # every failed result closes its goal.
        tick = _st.ScriptTick.__new__(_st.ScriptTick)
        tick.last_result = None
        tick._hold_result(_rc.ScriptResult(
            "script", result={"text": '{"done": false}', "truncated": False}))
        self.assertIs(tick.last_result["ok"], False)


class TestDeclaredQueriesReachTheRunner(unittest.TestCase):
    """A script's `queries = [...]` is fetched pre-tick and sent on the
    envelope as `queries` (change script-lookups-and-results, owner A2).

    The runner reads its context from `body.snapshot` alone, so the envelope
    is the only channel that needs no runner protocol change; these tests pin
    what actually goes across, which is the part a unit test of the parser
    cannot see.
    """

    def _capture(self):
        box = {}

        def _post(path, data=None, **kw):
            box["data"] = data
            return {"contract_version": 1, "status": "ok", "actions": []}
        return box, _post

    def test_declared_queries_ride_on_the_envelope(self):
        class Api(_FakeApi):
            def find_blocks(self, bot, block, radius=32, max_count=10):
                # The REAL mod shape (HttpApiServer.java:1126): a list under
                # `blocks`, with no `ok`, no `kind` and no `matches`. A stub
                # that answers `matches` directly hides the rename the agent
                # owes the script, which is how the 2026-11-27 live probe
                # read `matches` as undefined from an `ok: true` result.
                return {"blocks": [{"id": block, "x": 1, "y": -50, "z": 2}]}

        box, post = self._capture()
        src = ("queries = [{name: 'ore', kind: 'blocks', id: 'minecraft:diamond_ore'}];\n"
               "api.log('hi')")
        ScriptTick(Api(), "Scout", src, post=post).tick()
        env = box["data"]["snapshot"]
        self.assertEqual(env["queries"]["ore"]["matches"][0]["id"], "minecraft:diamond_ore")
        self.assertEqual(env["queries"]["ore"]["ok"], True)
        self.assertEqual(env["queries"]["ore"]["kind"], "blocks")
        # The mod's own key is renamed AWAY, not mirrored: two spellings of
        # one answer is how the drift this fix removes would start again.
        self.assertNotIn("blocks", env["queries"]["ore"])

    def test_an_entities_result_is_renamed_too(self):
        class Api(_FakeApi):
            def find_entities(self, bot, target, radius=32):
                return {"entities": [{"type": target, "x": 4, "y": -60, "z": 9}]}

        box, post = self._capture()
        src = "queries = [{name: 'cow', kind: 'entities', id: 'minecraft:cow'}];"
        ScriptTick(Api(), "Scout", src, post=post).tick()
        got = box["data"]["snapshot"]["queries"]["cow"]
        self.assertEqual(got["matches"][0]["type"], "minecraft:cow")
        self.assertEqual(got["ok"], True)
        self.assertNotIn("entities", got)

    def test_a_list_answer_missing_its_list_is_an_error_not_empty(self):
        # "searched, found nothing" and "the answer was not a list" are
        # different conclusions; reporting the second as an empty `matches`
        # would tell the script the world is empty when it was not read.
        class Api(_FakeApi):
            def find_blocks(self, bot, block, radius=32, max_count=10):
                return {"ok": True}

        box, post = self._capture()
        src = "queries = [{name: 'ore', kind: 'blocks', id: 'minecraft:diamond_ore'}];"
        ScriptTick(Api(), "Scout", src, post=post).tick()
        got = box["data"]["snapshot"]["queries"]["ore"]
        self.assertEqual(got["ok"], False)
        self.assertEqual(got["reason"], "error")
        self.assertNotIn("matches", got)

    def test_an_answer_marked_failed_is_not_reported_as_a_success(self):
        # find_blocks now sends an error key on a failed search (the mod fix,
        # HttpApiServer find_blocks), so this is the reachable shape on a
        # broken search rather than a hypothetical. Without the guard at
        # script_tick.py:660 the answer would carry error="boom" AND ok=true --
        # a silent wrong answer on the day a real search broke.
        class Api(_FakeApi):
            def find_blocks(self, bot, block, radius=32, max_count=10):
                return {"blocks": [], "count": 0, "error": "boom"}

        box, post = self._capture()
        src = "queries = [{name: 'ore', kind: 'blocks', id: 'minecraft:diamond_ore'}];"
        ScriptTick(Api(), "Scout", src, post=post).tick()
        got = box["data"]["snapshot"]["queries"]["ore"]
        self.assertEqual(got["ok"], False)
        self.assertEqual(got["reason"], "error")
        # The live obligation is {ok, reason, message}. The mod sends the text
        # under `error`, and the normaliser mirrors it into `message`; `error`
        # stays put (two names for one string is a stated choice). Assert the
        # exact key set so the duplication is deliberate and would redden if
        # either the setdefault were removed or `error` were stripped.
        self.assertEqual(got["message"], "boom")
        self.assertEqual(got["error"], "boom")
        # `count` is the mod's own extra field and passes through untouched
        # (only the list key is renamed to `matches`); the rest are the rule's.
        self.assertEqual(
            set(got) - {"matches"},
            {"ok", "reason", "message", "error", "kind", "count"},
        )

    def test_an_entity_answer_marked_failed_is_not_reported_as_a_success(self):
        # The error-key rule is one rule for both search verbs -- the normaliser
        # reads the key without knowing which verb produced it. This exercises
        # the entities path, whose failure the Java change now also carries, so
        # a test written for find_blocks cannot be read as covering find_entities.
        class Api(_FakeApi):
            def find_entities(self, bot, target, radius=32):
                return {"entities": [], "error": "findEntities error: boom"}

        box, post = self._capture()
        src = "queries = [{name: 'cow', kind: 'entities', id: 'minecraft:cow'}];"
        ScriptTick(Api(), "Scout", src, post=post).tick()
        got = box["data"]["snapshot"]["queries"]["cow"]
        self.assertEqual(got["ok"], False)
        self.assertEqual(got["reason"], "error")
        # The mod's own text reaches the script as `message` (the live
        # obligation), and is still under `error` too. Direct assert: this
        # reddens if the setdefault("message", value["error"]) is removed.
        self.assertEqual(got["message"], "findEntities error: boom")
        self.assertEqual(
            set(got) - {"matches"},
            {"ok", "reason", "message", "error", "kind"},
        )

    def test_a_genuine_empty_entity_answer_is_still_a_success(self):
        # The converse on the entity path: {entities: []} with no error key is
        # "searched, found nothing", which must stay ok=true.
        class Api(_FakeApi):
            def find_entities(self, bot, target, radius=32):
                return {"entities": []}

        box, post = self._capture()
        src = "queries = [{name: 'cow', kind: 'entities', id: 'minecraft:cow'}];"
        ScriptTick(Api(), "Scout", src, post=post).tick()
        got = box["data"]["snapshot"]["queries"]["cow"]
        self.assertEqual(got["ok"], True)
        self.assertEqual(got["matches"], [])

    def test_a_genuine_empty_answer_is_still_a_success(self):
        # The failure guard must not turn "searched, found nothing" into an
        # error: that would be the same wrong conclusion in the other
        # direction, and a real empty search is the common case.
        class Api(_FakeApi):
            def find_blocks(self, bot, block, radius=32, max_count=10):
                return {"blocks": []}

        box, post = self._capture()
        src = "queries = [{name: 'ore', kind: 'blocks', id: 'minecraft:diamond_ore'}];"
        ScriptTick(Api(), "Scout", src, post=post).tick()
        got = box["data"]["snapshot"]["queries"]["ore"]
        self.assertEqual(got["ok"], True)
        self.assertEqual(got["matches"], [])

    def test_block_at_keeps_the_mods_own_fields(self):
        # A single answer is not a list: renaming anything here would destroy
        # the information the script asked for.
        class Api(_FakeApi):
            def block_at(self, bot, x, y, z):
                return {"block": "minecraft:stone", "x": x, "y": y, "z": z}

        box, post = self._capture()
        src = "queries = [{name: 'here', kind: 'block_at', x: 1, y: 2, z: 3}];"
        ScriptTick(Api(), "Scout", src, post=post).tick()
        got = box["data"]["snapshot"]["queries"]["here"]
        self.assertEqual(got["block"], "minecraft:stone")
        self.assertEqual(got["ok"], True)
        self.assertEqual(got["kind"], "block_at")
        self.assertNotIn("matches", got)

    def test_no_declaration_sends_no_queries_key(self):
        box, post = self._capture()
        ScriptTick(_FakeApi(), "Scout", "api.log('hi')", post=post).tick()
        self.assertNotIn("queries", box["data"]["snapshot"])

    def test_a_bad_declaration_is_refused_at_construction(self):
        # The module under test is loaded under its own name (_load), so its
        # exception class is NOT the one `import script_tick` would give.
        with self.assertRaises(_st.DeclaredQueriesError):
            ScriptTick(_FakeApi(), "Scout", "queries = lookup()", post=lambda *a, **k: None)

    def test_a_failed_read_does_not_stop_the_tick(self):
        import requests

        class Api(_FakeApi):
            def find_blocks(self, bot, block, radius=32, max_count=10):
                raise requests.exceptions.Timeout()

        box, post = self._capture()
        src = ("queries = [{name: 'ore', kind: 'blocks', id: 'minecraft:diamond_ore'}];")
        handled, actions, refusals, detail = ScriptTick(Api(), "Scout", src, post=post).tick()
        self.assertEqual(box["data"]["snapshot"]["queries"]["ore"]["reason"], "timeout")
        # The script still ran: the search failing is the script's business.
        # (Its own detail says it logged nothing; what matters is that the
        # tick reached the runner and was not failed BY the read.)
        self.assertNotIn("snapshot", detail)


if __name__ == "__main__":
    unittest.main(verbosity=2)

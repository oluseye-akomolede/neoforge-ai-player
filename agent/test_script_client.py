"""Tests for agent/script_client.py — directive names and the runner bound.

Plain unittest, standard library only (this repo's agent tests are runnable
scripts, not pytest; `pytest` is not installed and not required).

The tests that matter here are the §4.4 ones. A closed port fails fast and
proves nothing about a bounded wait: it exercises `connect refused`, which is
§4.3. The case an easy test misses is a listener that ACCEPTS the connection
and then never replies — the agent must give up at the bound and must not leave
a thread hanging.
"""

import importlib.util
import inspect
import json
import os
import socket
import threading
import time
import unittest

# Loaded by path, deliberately NOT `from agent.script_client import ...`.
# `agent/` has no __init__.py, so the name `agent` resolves to agent.py itself;
# importing `agent.script_client` therefore executes agent.py and drags in
# psycopg2 and uvicorn. That made this file unrunnable in any environment
# without the full agent dependencies -- including a reviewer's seat and CI --
# which is the one property a test must have to be evidence at all.
_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "script_client_under_test", os.path.join(_HERE, "script_client.py")
)
_sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sc)

DIRECTIVE_KINDS = _sc.DIRECTIVE_KINDS
SCRIPT_TIMEOUT = _sc.SCRIPT_TIMEOUT
STATE_FALLBACK_ERROR = _sc.STATE_FALLBACK_ERROR
STATE_FALLBACK_REFUSED = _sc.STATE_FALLBACK_REFUSED
STATE_FALLBACK_TIMEOUT = _sc.STATE_FALLBACK_TIMEOUT
STATE_SCRIPT = _sc.STATE_SCRIPT
UnknownDirective = _sc.UnknownDirective
call_runner = _sc.call_runner
normalise_directive_name = _sc.normalise_directive_name


# ── Directive names (condition 4 of the lead's OK) ──────────────────────────

class DirectiveNameTest(unittest.TestCase):

    def test_lowercase_is_normalised_to_upper(self):
        # The mod already upper-cases (HttpApiServer.java:1341), so lowercase
        # works today; the agent normalises so the two sides agree.
        self.assertEqual(normalise_directive_name("mine"), "MINE")
        self.assertEqual(normalise_directive_name("Mine"), "MINE")
        self.assertEqual(normalise_directive_name("MINE"), "MINE")

    def test_whitespace_is_stripped(self):
        self.assertEqual(normalise_directive_name("  mine\n"), "MINE")

    def test_say_is_not_a_directive_type(self):
        # Found while writing this test, and it contradicts M2-PLAN §3.3:
        # the plan picks `say` as the parity subject, but SAY is NOT a
        # DirectiveType. The mod's chat directives are CHANNEL (a directive
        # that channels an item/action) and the separate /chat endpoint
        # (api.py:217). A script cannot api.do("SAY").
        self.assertNotIn("SAY", DIRECTIVE_KINDS)
        with self.assertRaises(UnknownDirective):
            normalise_directive_name("say")
        self.assertIn("CHANNEL", DIRECTIVE_KINDS)

    def test_unknown_name_is_refused_and_named(self):
        # The mod would throw inside its handler and return a nameless 500.
        # Refusing here gives an error that says which name and how big the set is.
        with self.assertRaises(UnknownDirective) as ctx:
            normalise_directive_name("NOT_A_REAL_DIRECTIVE")
        msg = str(ctx.exception)
        self.assertIn("NOT_A_REAL_DIRECTIVE", msg)
        self.assertIn(str(len(DIRECTIVE_KINDS)), msg)

    def test_agent_side_verbs_are_outside_the_mod_set(self):
        # EQUIP/DROP/ASK_PLAYER etc. are real L3 vocabulary but are handled
        # agent-side (agent.py:905-942), not posted as DirectiveType. Refusing
        # them here is correct: the mod does not define them.
        for verb in ("DROP", "EQUIP_ALL"):
            self.assertNotIn(verb, DIRECTIVE_KINDS)

    def test_non_string_is_refused(self):
        for bad in (None, 42, ["MINE"]):
            with self.assertRaises(UnknownDirective):
                normalise_directive_name(bad)


# ── The bound (§4.3 / §4.4) ─────────────────────────────────────────────────

class _NeverReplies:
    """A listener that accepts and then says nothing.

    This is the §4.4 case: the TCP connect succeeds, so a `connect refused`
    test would never reach it. The agent must give up at the bound.
    """

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def _serve(self):
        try:
            while not self._stop.is_set():
                try:
                    conn, _ = self.sock.accept()
                except OSError:
                    return
                # Hold the connection open, reply never.
                conn.settimeout(5)
                self._stop.wait(5)
                conn.close()
        finally:
            pass

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass
        self._thread.join(timeout=2)


def _post_to(port, timeout):
    """A _post-shaped callable aimed at a local port, honouring the timeout."""
    import requests

    def _post(path, data=None, **kw):
        return requests.post(f"http://127.0.0.1:{port}{path}", json=data or {},
                             timeout=kw.get("timeout", timeout)).json()
    return _post


class BoundTest(unittest.TestCase):

    def test_script_timeout_is_300ms(self):
        # Pins the number the §1 measurement chose. If someone changes the
        # default without re-measuring, this fails rather than silently
        # returning to a value below the observed 139 ms worst case.
        self.assertEqual(SCRIPT_TIMEOUT, 0.3)

    def test_silent_runner_times_out_and_does_not_hang(self):
        # 4.4: accepted, never replies. Must return at ~the bound, as a
        # fallback, with the thread released.
        before_threads = set(threading.enumerate())
        with _NeverReplies() as srv:
            started = time.monotonic()
            result = call_runner(None, {"bot": "Scout"},
                                 post=_post_to(srv.port, SCRIPT_TIMEOUT))
            elapsed = time.monotonic() - started

        self.assertEqual(result.state, STATE_FALLBACK_TIMEOUT, result.detail)
        self.assertEqual(result.actions, [])
        # Generous upper bound: the point is "bounded", not a latency benchmark.
        self.assertLess(elapsed, 2.0, f"took {elapsed:.2f}s, bound was not enforced")
        self.assertGreaterEqual(elapsed, SCRIPT_TIMEOUT * 0.5,
                                "returned suspiciously fast - did it even connect?")
        # The waiting thread must be released, not left hanging.
        #
        # The first version of this assertion looked for a live thread whose
        # name contained "requests". That could never fail: requests.post is
        # synchronous and creates no thread at all, and a leaked thread would
        # be named Thread-N. The check was decoration. This compares the thread
        # set before and after, so a thread that is started and not joined -
        # whatever it is named - is visible. (reviewer, 12:14Z)
        after = set(threading.enumerate())
        leaked = after - before_threads - {threading.current_thread()}
        self.assertFalse(
            leaked,
            f"thread(s) still alive after the bound: {[t.name for t in leaked]}")

    def test_connection_refused_is_reported_not_raised(self):
        # 4.3: a closed port. Grab a port then close it.
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()

        result = call_runner(None, {"bot": "Scout"}, post=_post_to(port, SCRIPT_TIMEOUT))
        self.assertEqual(result.state, STATE_FALLBACK_REFUSED, result.detail)
        self.assertEqual(result.actions, [])

    def test_ok_returns_actions(self):
        def fake_post(path, data=None, **kw):
            self.assertEqual(kw.get("timeout"), SCRIPT_TIMEOUT,
                             "the bound must be passed explicitly, not inherited")
            return {"actions": [{"kind": "say", "text": "hello"}]}

        result = call_runner(None, {"bot": "Scout"}, post=fake_post)
        self.assertEqual(result.state, STATE_SCRIPT)
        self.assertEqual(result.actions, [{"kind": "say", "text": "hello"}])

    def test_malformed_body_is_a_fallback_not_a_crash(self):
        def fake_post(path, data=None, **kw):
            return {"actions": "not-a-list"}

        result = call_runner(None, {"bot": "Scout"}, post=fake_post)
        self.assertEqual(result.state, STATE_FALLBACK_ERROR)
        self.assertEqual(result.actions, [])

    def test_bound_is_passed_explicitly_not_inherited(self):
        # The regression this exists to catch: someone calls the helper
        # without the timeout and api._post's 5 s default silently applies.
        seen = {}

        def fake_post(path, data=None, **kw):
            seen["timeout"] = kw.get("timeout")
            return {"actions": []}

        call_runner(None, {"bot": "Scout"}, post=fake_post)
        self.assertEqual(seen["timeout"], SCRIPT_TIMEOUT)
        self.assertNotEqual(seen["timeout"], 5, "fell back to _post's 5 s default")

    def test_bound_cannot_be_overridden_by_a_caller(self):
        # The tests above pinned the bound's VALUE. None of them could see a
        # caller passing `timeout=5`: such a caller reaches exactly the 5 that
        # test_bound_is_passed_explicitly_not_inherited asserts against, and
        # the suite stays green while the bound is gone. (reviewer, 12:24Z)
        #
        # The fix was to stop making it a parameter, so the guard is now the
        # signature itself. Asserted by behaviour first, so this fails loudly
        # rather than quietly if the parameter ever comes back.
        with self.assertRaises(TypeError):
            call_runner(None, {"bot": "Scout"}, timeout=5, post=lambda *a, **k: {})

        # And the structural form of the same claim, which also covers the
        # case where someone reintroduces a differently-named override.
        params = inspect.signature(call_runner).parameters
        self.assertNotIn("timeout", params,
                         "call_runner regained a timeout override; the bound "
                         "is only safe if it cannot be passed in")
        self.assertNotIn("kw", params)
        self.assertFalse(
            [p for p in params.values() if p.kind is p.VAR_KEYWORD],
            "a **kwargs on call_runner would let a timeout through unnoticed")


if __name__ == "__main__":
    unittest.main(verbosity=2)

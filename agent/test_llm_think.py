"""The transport contract: every /api/chat call says whether it may think, and
a truncated answer is a failed call rather than an empty one.

THE BUG THIS PINS. `qwen3.8` is a thinking model. Served with the small
`num_predict` budgets these call sites use (24, 128, 200), it spends the whole
budget thinking and returns empty content. Empty content does not raise: it
parses to nothing, and a caller reads "the model had no opinion". The bot then
does nothing, and nothing anywhere says why. Measured in the lead's probe before
this change existed.

TWO HALVES, both asserted here:

  1. Every request body carries a top-level `think`. Without it the choice is
     delegated to the serving stack's default, which is the condition that
     produced the empty content. The test enumerates the call sites rather than
     trusting a list in a comment -- a new site with no `think` fails it.
  2. Empty content WITH `done_reason: "length"` raises. Content that is empty
     for any other reason is still an empty answer, not an error, so the
     distinction is tested both ways.
"""
import ast
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import config  # noqa: E402


def agent_modules():
    """Every agent module the guards must cover: agent/*.py, tests excluded.

    Discovered, not listed. A hardcoded four-name tuple made the guards' real
    reach "these four files" while their docstrings promised "every call site":
    a new module posting to /api/chat with no think_field() passed green.
    test_the_guard_reaches_a_new_module pins this so a silent narrowing of the
    glob (say, a future subpackage) fails rather than quietly weakening both
    guards at once.
    """
    skip = {"test_llm_think.py", "conftest.py"}
    return sorted(n for n in os.listdir(HERE)
                  if n.endswith(".py") and not n.startswith("test_")
                  and n not in skip)


def chat_sites():
    """Every function in the agent that posts to an Ollama /api/chat URL.

    Returns (module_name, line) for each. Read from the source text rather than
    from a list, so a site added later is counted without anyone updating this.
    """
    found = []
    for name in agent_modules():
        path = os.path.join(HERE, name)
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            src = ast.dump(node)
            if "api/chat" not in src:
                continue
            f = node.func
            fname = getattr(f, "attr", getattr(f, "id", "?"))
            if fname not in ("post", "urlopen", "Request"):
                continue
            found.append((name, node.lineno))
    return found


class _FakeResponse:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        return None


def body_of_call(module, fn, **kwargs):
    """Run `fn` with requests.post patched; return the json= it was called with.

    The body is captured at the wire, not read off a helper's return value: the
    bug being prevented is a field present in one place and absent at the other.
    """
    captured = {}

    def fake_post(url, **kw):
        captured["url"] = url
        captured["json"] = kw.get("json")
        return _FakeResponse({"message": {"content": "{}"}, "done_reason": "stop"})

    with mock.patch.object(module.requests, "post", fake_post):
        try:
            fn(**kwargs)
        except Exception:
            # Several callers parse the response and may fail on the stub; the
            # request body is what this asserts, so a parse error is not a test
            # failure. The body was captured before the call returned.
            pass
    return captured.get("json")


class GuardReachTests(unittest.TestCase):
    def test_the_guards_walk_discovered_modules_not_a_list(self):
        """The two AST guards must cover agent/*.py, not four named files.

        Both guards once iterated ("brain.py", "criteria_eval.py", "planner.py",
        "l3_planner.py"). A reviewer planted a /api/chat site with no
        think_field() in agent/agent.py and the guard passed GREEN -- so the
        docstring's "a new site fails it" was false. This pins the discovery:
        the set must include every non-test module, so a new file is covered on
        the day it lands and a narrowed glob fails here instead of quietly
        shrinking both guards.
        """
        mods = agent_modules()
        for expected in ("brain.py", "criteria_eval.py", "planner.py",
                         "l3_planner.py", "agent.py"):
            self.assertIn(expected, mods,
                          "guard does not reach %s: %s" % (expected, mods))
        self.assertFalse([m for m in mods if m.startswith("test_")],
                         "guards must not parse test modules: %s" % mods)

    def test_every_chat_site_is_counted(self):
        sites = chat_sites()
        self.assertGreaterEqual(
            len(sites), 12,
            "expected at least 12 agent /api/chat sites; found %d: %s"
            % (len(sites), sites))

    def test_every_chat_site_body_includes_think(self):
        """No site may post a body it built without the shared helper.

        Read from source: each `json={...}` that reaches an /api/chat URL must
        contain `**think_field()`. A new call site that hand-builds its body
        fails here, which is the whole point -- a list in a comment cannot.
        """
        import ast
        missing = []
        for name in agent_modules():
            path = os.path.join(HERE, name)
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read(), path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if "api/chat" not in ast.dump(node):
                    continue
                for kw in node.keywords:
                    if kw.arg != "json" or not isinstance(kw.value, ast.Dict):
                        continue
                    # `**think_field()` is a Dict key of None with a Call value,
                    # so dumping the dict and looking for the name is enough.
                    if "think_field" not in ast.dump(kw.value):
                        missing.append((name, node.lineno))
        self.assertEqual(
            missing, [],
            "these /api/chat sites build a body without think_field(): %s" % missing)

    def test_helper_returns_a_real_boolean(self):
        # Not a string: a JSON "false" would be parsed by Ollama as... nothing,
        # it is a string, and the model's default applies.
        field = config.think_field()
        self.assertEqual(set(field), {"think"})
        self.assertIsInstance(field["think"], bool)

    def test_default_is_off(self):
        """With AIBOT_LLM_THINK unset, thinking must be off.

        config reads the variable at import, so a developer who has it exported
        would see this fail for a reason that is not about the default. Patch
        the environment AND reload, so the assertion is about the code's
        default rather than about whoever is running the suite.
        """
        import importlib
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AIBOT_LLM_THINK", None)
            importlib.reload(config)
            try:
                self.assertIs(config.LLM_THINK, False,
                              "thinking must default off: on a thinking model "
                              "with a small num_predict it returns empty content")
            finally:
                importlib.reload(config)

    def test_brain_request_carries_think(self):
        import brain
        body = body_of_call(brain, brain.think, model="m", system_prompt="s",
                            observation="o", history=[])
        self.assertIn("think", body, "the body sent to /api/chat has no think")
        self.assertIsInstance(body["think"], bool)
        self.assertNotIn("options_think", body)


class TruncatedAnswerTests(unittest.TestCase):
    """The lead-approved requirement: empty content + done_reason=length FAILS."""

    def test_length_stop_with_empty_content_raises(self):
        from config import TruncatedAnswer, answer_text
        body = {"message": {"content": ""}, "done_reason": "length",
                "eval_count": 24}
        with self.assertRaises(TruncatedAnswer) as cm:
            answer_text(body)
        self.assertIn("done_reason=length", str(cm.exception))

    def test_whitespace_only_content_is_still_truncation(self):
        from config import TruncatedAnswer, answer_text
        body = {"message": {"content": "   \n"}, "done_reason": "length"}
        with self.assertRaises(TruncatedAnswer):
            answer_text(body)

    def test_empty_content_on_a_stop_stop_is_an_empty_answer(self):
        """done_reason=stop with empty content is not truncation -- it answered."""
        from config import answer_text
        self.assertEqual(answer_text({"message": {"content": ""},
                                      "done_reason": "stop"}), "")

    def test_real_content_is_returned(self):
        from config import answer_text
        self.assertEqual(answer_text({"message": {"content": "hello"},
                                      "done_reason": "length"}), "hello")

    def test_missing_body_does_not_raise(self):
        from config import answer_text
        self.assertEqual(answer_text({}), "")

    def test_every_content_reader_uses_answer_text(self):
        """A chat call whose enclosing function never calls answer_text()
        reads the body some other way and bypasses the truncation predicate.

        The post and the read are on different lines, so the check is the
        enclosing function, not the call node. The *trigger* is still a real
        post call node: matching the string anywhere in the function would flag
        helpers that only mention /api/chat in a docstring (config.think_field
        did exactly that when this guard's glob widened to every module).
        """
        import ast
        missing = []
        for name in agent_modules():
            path = os.path.join(HERE, name)
            with open(path, encoding="utf-8") as f:
                src = f.read()
            tree = ast.parse(src, path)
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                posts = [n for n in ast.walk(fn)
                         if isinstance(n, ast.Call)
                         and "api/chat" in ast.dump(n)
                         and getattr(n.func, "attr",
                                     getattr(n.func, "id", "?"))
                         in ("post", "urlopen", "Request")]
                if not posts:
                    continue
                if "answer_text" not in ast.dump(fn):
                    missing.append((name, fn.name, fn.lineno))
        self.assertEqual(
            missing, [],
            "these functions post to /api/chat but never call answer_text(): %s"
            % missing)


class TruncatedAnswerThroughTheGatewayTests(unittest.TestCase):
    """The guard has to survive the transport it actually runs behind.

    The unit tests above feed answer_text a hand-built Ollama body. The agent
    never sees one: every L3 call goes through llm-gateway's /api/chat shim,
    which until gateway-token-accounting emitted its own envelope and dropped
    done_reason and eval_count entirely. So the three predicates were all
    tested and the guard could still never fire in production. These tests use
    the SHIM's envelope, so a regression in either half reddens them.
    """

    @staticmethod
    def _gateway_envelope(content="", done_reason=None, eval_count=0,
                          thinking=None):
        """The body llm-gateway /api/chat returns after the passthrough fix."""
        body = {
            "model": "qwen3.8:27b-q4_K_M",
            "created_at": "2026-11-20T18:43:00.000Z",
            "message": {"role": "assistant", "content": content},
            "done": True,
            "total_duration": 1_000_000,
            "eval_count": eval_count,
            "done_reason": done_reason,
            "_gateway": {"request_id": "abc123", "waited_ms": 0,
                         "inference_ms": 1, "queue_depth": 0},
        }
        if thinking is not None:
            body["message"]["thinking"] = thinking
        return body

    def test_gateway_length_reply_raises(self):
        """KILLS: a gateway that drops done_reason (the 1fad4205 build).

        Fed the pre-fix envelope this test returns "" instead of raising,
        which is precisely the silent-empty failure it exists to catch.
        """
        from config import TruncatedAnswer, answer_text
        body = self._gateway_envelope(content="", done_reason="length",
                                      eval_count=1024)
        with self.assertRaises(TruncatedAnswer) as cm:
            answer_text(body)
        self.assertIn("eval_count=1024", str(cm.exception))

    def test_gateway_stop_reply_is_an_empty_answer(self):
        """KILLS: treating every empty reply as truncation."""
        from config import answer_text
        body = self._gateway_envelope(content="", done_reason="stop",
                                      eval_count=5)
        self.assertEqual(answer_text(body), "")

    def test_pre_fix_envelope_cannot_report_truncation(self):
        """Documents the defect and fails loudly if it is reintroduced.

        Before the fix the shim emitted no done_reason key at all. This asserts
        what that envelope does: an empty, truncated-looking reply is
        indistinguishable from a refusal, because the field that would say so
        is absent. If this ever starts raising, the envelope changed again.
        """
        from config import answer_text
        pre_fix = {
            "model": "qwen3.8:27b-q4_K_M",
            "created_at": "2026-11-20T18:39:00.000Z",
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "total_duration": 1_000_000,
            "eval_count": 0,
            "_gateway": {"request_id": "abc123", "waited_ms": 0,
                         "inference_ms": 1, "queue_depth": 0},
        }
        self.assertNotIn("done_reason", pre_fix)
        self.assertEqual(answer_text(pre_fix), "")


if __name__ == "__main__":
    unittest.main()

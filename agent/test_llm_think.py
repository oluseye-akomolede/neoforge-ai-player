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


def chat_sites():
    """Every function in the agent that posts to an Ollama /api/chat URL.

    Returns (module_name, line) for each. Read from the source text rather than
    from a list, so a site added later is counted without anyone updating this.
    """
    found = []
    for name in ("brain.py", "criteria_eval.py", "planner.py", "l3_planner.py"):
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


class ThinkFieldTests(unittest.TestCase):
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
        for name in ("brain.py", "criteria_eval.py", "planner.py", "l3_planner.py"):
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
        self.assertIs(config.LLM_THINK, False,
                      "thinking must default off: on a thinking model with a "
                      "small num_predict it returns empty content")

    def test_brain_request_carries_think(self):
        import brain
        body = body_of_call(brain, brain.think, model="m", system_prompt="s",
                            observation="o", history=[])
        self.assertIn("think", body, "the body sent to /api/chat has no think")
        self.assertIsInstance(body["think"], bool)
        self.assertNotIn("options_think", body)


class TruncatedAnswerTests(unittest.TestCase):
    def test_empty_content_with_done_reason_length_raises(self):
        with self.assertRaises(config.TruncatedAnswer):
            config.answer_text({"message": {"content": ""},
                                "done_reason": "length", "eval_count": 24})

    def test_whitespace_only_with_length_also_raises(self):
        # A thinking model can stop having emitted only whitespace.
        with self.assertRaises(config.TruncatedAnswer):
            config.answer_text({"message": {"content": "  \n "},
                                "done_reason": "length"})

    def test_empty_content_without_length_is_still_an_empty_answer(self):
        # The distinction must not collapse: a model that genuinely said nothing
        # is not a truncation, and turning that into an error would hide it.
        self.assertEqual(
            config.answer_text({"message": {"content": ""},
                                "done_reason": "stop"}), "")

    def test_normal_answer_is_returned_unchanged(self):
        self.assertEqual(
            config.answer_text({"message": {"content": '{"a": 1}'},
                                "done_reason": "length"}),
            '{"a": 1}',
            "a truncated but non-empty answer is still usable -- only an empty "
            "one is a failed call")

    def test_missing_body_does_not_raise(self):
        self.assertEqual(config.answer_text({}), "")
        self.assertEqual(config.answer_text(None), "")


if __name__ == "__main__":
    unittest.main()


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
        enclosing function, not the call node.
        """
        import ast
        missing = []
        for name in ("brain.py", "criteria_eval.py", "planner.py", "l3_planner.py"):
            path = os.path.join(HERE, name)
            with open(path, encoding="utf-8") as f:
                src = f.read()
            tree = ast.parse(src, path)
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                dump = ast.dump(fn)
                if "api/chat" not in dump:
                    continue
                if "answer_text" not in dump:
                    missing.append((name, fn.name, fn.lineno))
        self.assertEqual(
            missing, [],
            "these functions post to /api/chat but never call answer_text(): %s"
            % missing)

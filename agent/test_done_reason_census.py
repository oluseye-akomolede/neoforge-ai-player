"""Every structured call fails on a length stop, including a non-empty cut.

The rule: a reply stopped for length is a failed call, not a short answer. The
census (tools/census_structured_calls.py) counts the sites; these tests prove
the shared guard actually reads the field, and that a site using it really does
refuse a cut reply instead of substituting a plausible one.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

import config
import brain
import planner


class _Resp:
    """A stand-in requests response carrying a chosen body."""

    def __init__(self, body):
        self._body = body
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


def _reply(content, done_reason="stop", eval_count=7):
    return {"message": {"content": content}, "done_reason": done_reason,
            "eval_count": eval_count}


class SharedGuardTest(unittest.TestCase):

    def test_a_length_stop_raises(self):
        with self.assertRaises(config.TruncatedAnswer) as cm:
            config.ensure_not_truncated(_reply('{"a": 1', "length"), "probe")
        self.assertIn("probe", str(cm.exception))
        self.assertIn("done_reason=length", str(cm.exception))

    def test_a_normal_stop_passes(self):
        config.ensure_not_truncated(_reply("{}", "stop"), "probe")

    def test_a_missing_done_reason_passes(self):
        """Older gateways dropped the field. Absent is not 'length': failing
        every call would be worse than the truncation it guards against."""
        config.ensure_not_truncated({"message": {"content": "{}"}}, "probe")

    def test_a_non_dict_body_passes_rather_than_crashing(self):
        config.ensure_not_truncated(None, "probe")
        config.ensure_not_truncated("not a body", "probe")

    def test_the_guard_is_named_what_the_census_looks_for(self):
        """The census recognises the guard BY NAME. If the helper is renamed,
        the census silently stops counting it and would report sites as guarded
        that are not -- or, after the rename, as unguarded and be "fixed" by
        inlining. Pin the name the census matches."""
        census_src = open(os.path.join(os.path.dirname(__file__),
                                       "tools", "census_structured_calls.py")).read()
        self.assertIn('"ensure_not_truncated"', census_src)
        self.assertTrue(callable(getattr(config, "ensure_not_truncated", None)))


class SitesRefuseACutReplyTest(unittest.TestCase):
    """End-to-end: the sites whose parse-failure substituted a plausible result
    now refuse instead. These are the three the census singled out."""

    def _patch_post(self, module, body):
        calls = {}

        def fake_post(url, **kw):
            calls["url"] = url
            return _Resp(body)

        self.addCleanup(setattr, module.requests, "post", module.requests.post)
        module.requests.post = fake_post
        return calls

    def test_brain_think_refuses_a_cut_reply(self):
        # KILLS: the substituted {"thoughts": "Failed to parse response"}.
        body = _reply('{"thoughts": "I should mine', "length")
        self._patch_post(brain, body)
        with self.assertRaises(config.TruncatedAnswer):
            brain.think("m", "sys", "obs", [])

    def test_planner_decompose_refuses_a_cut_reply(self):
        body = _reply('{"steps": ["go to the', "length")
        self._patch_post(planner, body)
        with self.assertRaises(config.TruncatedAnswer):
            planner.decompose("m", "go somewhere")

    def test_planner_orchestrate_refuses_a_cut_reply(self):
        body = _reply('{"steps": [{"step": "min', "length")
        self._patch_post(planner, body)
        with self.assertRaises(config.TruncatedAnswer):
            planner.orchestrate("m", "do a thing",
                                [{"name": "Scout", "specializations": ["scout"]}])

    def test_a_cut_reply_is_not_silently_substituted(self):
        """The specific regression: before the guard, a length stop produced a
        RESULT, and the result looked like work. Assert we do not get one."""
        body = _reply('{"thoughts": "partial', "length")
        self._patch_post(brain, body)
        try:
            result = brain.think("m", "sys", "obs", [])
        except config.TruncatedAnswer:
            return
        self.fail(f"a length stop produced a result instead of failing: {result!r}")


class CensusTest(unittest.TestCase):

    def test_the_census_is_green(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        out = subprocess.run([sys.executable, "-B",
                              os.path.join("agent", "tools", "census_structured_calls.py")],
                             cwd=here, capture_output=True, text=True)
        self.assertEqual(0, out.returncode,
                         f"census drifted:\n{out.stdout}\n{out.stderr}")
        self.assertIn("guarded=9 unguarded=0", out.stdout)

    def _run(self, args, cwd, absolute=False):
        script = os.path.join("agent", "tools", "census_structured_calls.py")
        if absolute:
            script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                  "agent", "tools", "census_structured_calls.py")
        return subprocess.run([sys.executable, "-B", script, *args],
                              cwd=cwd, capture_output=True, text=True)

    def test_an_unknown_flag_is_refused_not_ignored(self):
        """A caller passing --root believes it measured that root. The census
        walks ./agent regardless, so ignoring the flag hands back a count for a
        tree nobody named. Refuse, and say so."""
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        out = self._run(["--root", "/tmp/nonexistent"], here)
        self.assertEqual(2, out.returncode,
                         f"expected refusal, got {out.returncode}:\n{out.stdout}{out.stderr}")
        self.assertIn("takes no arguments", out.stderr)
        self.assertNotIn("functions=0", out.stdout)

    def test_running_outside_the_repo_root_is_refused(self):
        """Without agent/ the census finds nothing and would print functions=0
        -- a count for a tree it never read."""
        out = self._run([], "/tmp", absolute=True)
        self.assertEqual(2, out.returncode,
                         f"expected refusal, got {out.returncode}:\n{out.stdout}{out.stderr}")
        self.assertIn("must run from the repo root", out.stderr)
        self.assertNotIn("functions=0", out.stdout)


if __name__ == "__main__":
    unittest.main()

"""The planner can answer with a script instead of a step list.

Step (a) of the ai-written-scripts change makes the planner an author of
programs: `decompose` may return a script the agent runs directly, carried in
memory and never written to disk (spec: "A Planner-Authored Script Lives In
Memory, Not On Disk").

The contract these tests pin is deliberately narrow and additive. `decompose`
returns a list of step strings today and every caller iterates it as a list.
So the script is returned as a `PlannerResult` that IS a list of steps (the
fallback path stays byte-identical for every non-script answer) and carries the
script source as an attribute. A caller that knows nothing about scripts sees
exactly what it saw before.

Every test names the wrong implementation it kills, so a later reader can
re-run the experiment rather than trust the green.
"""

import json
import unittest
from unittest.mock import patch

import planner


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _ollama_body(content):
    return {"message": {"content": content}, "done_reason": "stop"}


def _decompose_with(content):
    """Run decompose against a canned model answer, no network."""
    with patch.object(planner.requests, "post",
                      return_value=_FakeResponse(_ollama_body(content))), \
         patch.object(planner, "openai_brain") as fake_l4:
        fake_l4.is_available.return_value = False
        return planner.decompose("test-model", "chop a tree")


class ScriptOutputTest(unittest.TestCase):
    def test_a_script_answer_is_carried_and_not_stored(self):
        # KILLS: a parser that only reads "steps" and drops a "script" key on
        # the floor -- which is what the code did before this change, so the
        # planner could answer with a program and the agent would run the
        # program's TEXT as a step string forever.
        src = "api.do('minecraft:mine_stone', {x:1,y:2,z:3});"
        result = _decompose_with(json.dumps({"script": src}))

        self.assertEqual(result.script, src,
                         "the planner's script source must survive parsing")
        self.assertEqual(list(result), [],
                         "a script answer has no step list to execute")

    def test_a_step_answer_is_unchanged_and_has_no_script(self):
        # KILLS: returning a script for every answer, or wrapping the step list
        # so a caller iterating it sees something other than the step strings.
        result = _decompose_with(json.dumps({"steps": ["walk to tree", "chop"]}))

        self.assertEqual(list(result), ["walk to tree", "chop"])
        self.assertIsNone(result.script,
                          "a step answer must not look like a script answer")

    def test_a_truncated_step_answer_still_falls_back(self):
        # KILLS: making the script path mandatory, so an ordinary malformed
        # answer stops returning the instruction as a single step.
        result = _decompose_with("not json at all")

        self.assertEqual(list(result), ["chop a tree"])
        self.assertIsNone(result.script)

    def test_the_script_never_reaches_a_file_write(self):
        # KILLS: an implementation that "helpfully" persists the script --
        # the spec forbids it (no write path exists in the agent), and a
        # persisted script would silently outlive the process that made it.
        src = "api.do('minecraft:mine_stone', {x:1,y:2,z:3});"
        with patch("builtins.open") as fake_open:
            result = _decompose_with(json.dumps({"script": src}))
        self.assertEqual(result.script, src)
        self.assertFalse(fake_open.called,
                         "decompose must not open any file, for write or read")


if __name__ == "__main__":
    unittest.main()

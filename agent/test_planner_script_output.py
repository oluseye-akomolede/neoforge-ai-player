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


def _rendered_prompt():
    """The prompt EXACTLY as the model receives it.

    Rendered through production's own renderer, `planner.render_planner_prompt`,
    not re-encoded here: a test that rebuilds the render can share the render's
    bug and cannot observe it (reviewer F-1, 2026-11-21: my first version did
    exactly that and passed while both prompts carried {{ok, seq}}).
    """
    return planner.render_planner_prompt()


def _assert_no_doubled_braces(testcase, rendered, where):
    testcase.assertNotIn("{{", rendered, f"doubled open brace reaches the model in {where}")
    testcase.assertNotIn("}}", rendered, f"doubled close brace reaches the model in {where}")


class PlannerPromptDocumentsPtcTest(unittest.TestCase):
    def test_the_rendered_prompt_has_no_doubled_braces(self):
        """KILLS: the regression where SCRIPT_SURFACE was moved out of the
        .format template but kept its escaped {{ }}, so the MODEL read
        "Returns {{ok, seq}} or a rejection." Seven artefacts, on both
        prompts. Every assertion in this file passed while that shipped,
        because they render through the same path the bug lived in."""
        p = _rendered_prompt()
        _assert_no_doubled_braces(self, p, "the legacy planner prompt")
        # the real shapes must be there as literals, not just "no braces"
        self.assertIn("Returns `{ok, seq}` or a rejection", p)
        self.assertIn("`{ok: true, kind: 'blocks', matches: [...]}`", p)
        self.assertIn("`{id, block, position}`", p)

    def test_the_prompt_documents_look_and_result(self):
        # KILLS: the shipped gap -- the script section listed only the six
        # api.* calls, so no planner-written script could use lookups (b) or
        # report a result (c). A prompt that does not name a call is a call
        # the model never writes.
        prompt = _rendered_prompt()

        for needed in ("look.blocks(", "look.entities(", "look.age()",
                       "look.task(", "api.result("):
            self.assertIn(needed, prompt,
                          f"the planner prompt must name {needed}")

    def test_the_prompt_names_the_fields_look_task_actually_returns(self):
        # KILLS (review F-1 on 465b61e): the prompt told scripts to check
        # arrival against a result no lookup returned. The documented field
        # names are pinned to the runner's own lookup, so a prompt that names
        # a field look.task() does not carry fails here rather than in a
        # spin-the-tick script.
        surface = planner.SCRIPT_SURFACE
        self.assertIn("look.task()", surface)
        for field in ("arrived_at", "adjusted_from", "adjusted_to",
                      "failure_reason", "COMPLETED", "FAILED"):
            self.assertIn(field, surface,
                          f"SCRIPT_SURFACE must name {field}, which look.task() "
                          f"returns to a script")

    def test_the_prompt_says_do_ok_is_acceptance_not_completion(self):
        # KILLS: the whole reason F-1 went unnoticed -- `{ok: true, seq}` reads
        # like success. A prompt that omits this leaves a script believing
        # `ok` means the action happened.
        surface = planner.SCRIPT_SURFACE
        self.assertIn("ACCEPTED", surface)
        self.assertIn("never means it", surface)

    def test_the_prompt_states_look_is_free_and_result_is_not(self):
        # KILLS: listing the calls without the budget rule, which would have a
        # script hoard lookups it does not pay for and spend result calls it
        # does. api.result calls accept(); look answers from the snapshot.
        prompt = _rendered_prompt()
        budget = prompt[prompt.index("At most 8 host calls"):][:400]
        charged, _, free = budget.partition(" each count")
        self.assertTrue(free, "the budget line must say which calls count")

        # Each call is asserted on the side of the divide it belongs to. A
        # bare `assertIn` cannot do this: a mutant that moves api.result into
        # the free list leaves the word present and the test green.
        self.assertIn("api.result", charged,
                      "api.result costs one of the 8 host calls")
        self.assertNotIn("look", charged,
                         "look is not a host call and must not be charged")
        self.assertIn("look", free, "look must be stated as free")
        self.assertIn("free", free.lower())

    def test_the_prompt_states_the_real_radii_and_the_not_searched_answer(self):
        # KILLS: a prompt that offers lookups without their reach, so the
        # model reads an empty answer as "nothing there" instead of "I did not
        # look that far" -- and writing an invented radius here.
        prompt = _rendered_prompt()

        # Both radii tied to their own sentence. A bare assertIn("16") passes
        # on any of the prompt's other sixteens ("Craft 16x", "Y=16",
        # "<=16 KB"), so entities 16 -> 15 would stay green (reviewer F-1).
        self.assertIn("blocks within 5 blocks", prompt)
        self.assertIn("entities within 16", prompt)
        self.assertIn("not-searched-that-far", prompt)

    def test_the_prompt_states_the_result_journey(self):
        # KILLS: naming api.result without saying when it arrives, that the
        # last call wins, the cap, or that the return value is discarded --
        # the three facts a script author would otherwise get wrong.
        prompt = _rendered_prompt()

        self.assertIn("discarded", prompt,
                      "the top-level return value is not the result")
        self.assertIn("LAST call", prompt)
        self.assertIn("2 KiB", prompt)
        self.assertIn("escalate", prompt)

    def test_the_prompt_warns_goto_takes_a_position_not_a_block(self):
        # KILLS: trial 4.2. A script targeted an enclosed ore block itself, the
        # mod lifted the destination 36 blocks to the surface, and the script
        # had no way to learn the target had moved. The prompt must say GOTO is
        # a position and to stand NEXT TO a block to work on it. Also pins the
        # failure name so a planner can recognise it.
        prompt = _rendered_prompt()

        self.assertIn("GOTO` goes to a POSITION, not to a block", prompt,
                      "the prompt must say GOTO takes a position, not a block")
        self.assertIn("neighbouring open block", prompt,
                      "the prompt must say to stand next to the block")
        self.assertIn("target_enclosed", prompt,
                      "a planner must be able to recognise the enclosed failure")
        self.assertIn("adjusted_from", prompt,
                      "a planner must know a lifted destination is reported")


class PlannerPromptRendersTest(unittest.TestCase):
    def test_the_real_prompt_renders_and_reaches_the_model(self):
        # KILLS: a brace typo in the new section -- `.format` would raise, or
        # silently mangle the text. Asserts the model's own request body has
        # the calls, so this covers the rendered path, not the constant.
        sent = {}

        def capture(url, json=None, **kw):
            sent["prompt"] = json["messages"][0]["content"]
            return _FakeResponse(_ollama_body('{"steps": ["walk"]}'))

        with patch.object(planner.requests, "post", side_effect=capture), \
                patch.object(planner, "openai_brain") as fake_l4:
            fake_l4.is_available.return_value = False
            planner.decompose("test-model", "chop a tree")

        for needed in ("look.blocks(", "look.entities(", "look.age()",
                       "look.task(", "api.result("):
            self.assertIn(needed, sent["prompt"])


class GotoWarningTest(unittest.TestCase):
    """A script writing a GOTO must be told it takes a POSITION, that a solid
    target fails rather than digs, and where to read a lift -- trial 4.2 was a
    GOTO silently lifted 36 blocks to the surface."""

    def test_the_prompt_warns_that_a_solid_goto_target_fails(self):
        surface = planner.SCRIPT_SURFACE
        self.assertIn("target_enclosed", surface)
        self.assertIn("POSITION, not to a block", surface)

    def test_the_prompt_names_where_a_lift_is_reported(self):
        self.assertIn("`adjusted_from`", planner.SCRIPT_SURFACE)
        self.assertIn("`adjusted_to`", planner.SCRIPT_SURFACE)

    def test_the_prompt_lift_bound_matches_the_mod(self):
        # The prompt states the bound as a literal. Pin it to the Java constant
        # so the two cannot drift: a script author reading "3" and a mod that
        # lifts 5 is the same class of false statement as the fixture.
        import pathlib
        import re
        src = pathlib.Path(__file__).resolve().parent.parent / (
            "src/main/java/com/sigmastrain/aiplayermod/brain/behavior/GotoBehavior.java")
        m = re.search(r"GOTO_MAX_LIFT\s*=\s*(\d+)", src.read_text())
        self.assertIsNotNone(m, "GOTO_MAX_LIFT not found in GotoBehavior.java")
        self.assertIn(f"lifted up to {m.group(1)} blocks", planner.SCRIPT_SURFACE)


if __name__ == "__main__":
    unittest.main()

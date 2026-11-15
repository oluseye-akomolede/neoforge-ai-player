# Review — 5ee0406 (planner-prompt-declines step 2)

**Verdict: PASS**, with one test-quality finding (T1) that I recommend fixing now
because it is one line and it pins the clause the lead just ruled on.

Reviewed `5ee0406` from a `git bundle` of `minecraft-wt-deepseek` in a scratch
clone, not the builder's tree. Parent `25b9fc1` (delta as amended). Range:
`git diff 25b9fc1 5ee0406` = 3 files, +129/-15.

## What I checked, and how

**Prompt text matches the rulings.** `_REPLAN_SYSTEM_PROMPT` loses
`If truly impossible, return: {"error": ...}` and gains the one-replacement-subtask
MUST plus retry directions. `_PLAN_SYSTEM_PROMPT` gains the transient-state
paragraph and the speech-is-not-a-directive paragraph. `_REFINE_SKILL_PROMPT`
untouched, per the lead's out-of-scope line.

The planned-around wording carries the lead's 11:01Z ruling verbatim in the
prompt: prerequisites that deliver the exact goal, never a nearby goal, decline
if no such path exists.

**Format safety — verified by execution, not by reading.** The builder reported
"verified to `.format()` cleanly". I ran the real call sites with the real
argument names (`:418` for plan, `:1008` for replan):

    PLAN ok len 6540; REPLAN ok len 675

Both format cleanly and the new rules survive `.format()` (braces are doubled
in the clarify/refuse examples, so an unescaped brace would have raised). This
matters more than it looks: an unescaped brace here crashes every plan call at
runtime while passing any text-only test.

**Mutation testing — every added rule is pinned.** Deleting the new paragraph,
the speech rule, the no-substitution clause, or reopening the replan error hatch
each reddens a named test:

    [delete transient-state paragraph]     RED: test_transient_state_is_planned_around
    [delete speech rule]                   RED: test_speech_is_not_a_directive
    [reopen replan error hatch]            RED: test_replan_demands_one_subtask,
                                                test_replan_has_no_error_escape_hatch
    [drop no-substitution rule]            RED: test_planning_around_is_not_substitution
    [soften MUST decline -> may decline]   RED: test_no_prerequisite_path_means_decline
    [remove all clarify examples]          RED: test_clarify_examples_survive
    [remove all moon examples]             RED: test_correct_refusal_examples_survive

The correct refusals are genuinely untouched: moon, simultaneity and both
clarify examples are intact textually and pinned by tests that die when removed.
The builder's claim on this point holds.

**Test suite at 5ee0406** (scratch clone): `test_planner_prompts` 10 tests OK,
control run after every mutation restored green.

## T1 — unpinned clause (one line; not a blocker, but fix it)

`test_no_prerequisite_path_means_decline` asserts only:

```python
self.assertIn("you MUST decline", text)
```

That exact phrase is **pre-existing** — `l3_planner.py:363`, part of the
substitution paragraph that predates this change. It occurs once in the file.
So the test passes on text the commit did not add.

Proof: deleting the entire new decline clause
(`If no prerequisite path can deliver the stated goal, decline rather than substituting.`)
leaves all 10 tests green.

Why it matters beyond tidiness: that clause is the one the lead ruled on at
11:01Z. It is the sentence that stops "plan around it" from becoming "never
refuse". Right now nothing would catch its removal.

Fix: assert the new sentence, e.g.

```python
self.assertIn("If no prerequisite path can deliver the stated goal, decline", text)
```

which is whitespace-normalised-safe under `_norm`.

## Not disputed

- Step-2 scope: correct. Only the three files the row names.
- `_REFINE_SKILL_PROMPT` behaviour preserved; `RefineSkillSiblingIsOutOfScope`
  records the known sibling as the lead directed.
- tasks.md ticks 1.1-1.4, 2.1-2.4 (incl 2.2a), 3.1-3.4; 4.x open — consistent
  with "step 2 of 3".

## Notes on my own process

Two mutations first came back green and both were my harness, not the tests:
a heredoc `printf`-style arg passing that never applied the mutation, and
`count=1` on strings that appear twice in the prompt. I re-ran on
whitespace-normalised, all-occurrence substitution before believing any result.
An implausible all-green was the signal both times.

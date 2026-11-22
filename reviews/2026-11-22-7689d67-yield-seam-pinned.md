# 7689d67: the driven seam is now a test — PASS

Rev reviewed: `7689d67` (parent `7c92a43`, which I passed).
Reviewer: minecraft-reviewer@minecraft. 2026-11-22.

**Verdict: PASS.** Two files, 35 insertions, no production code touched. The test
pins the exact seam I drove at `7c92a43` and reported as my evidence rather than
their coverage, and it pins it *better* than my probe did — one point where their
test is stronger than my original evidence, noted below.

## The test

`test_the_yield_refuses_a_goal_less_bot_at_its_own_seam` drives
`_yield_script_to_planner("spin: …")` directly on a goal-less runner and asserts
`orch_calls == 0`, `_plan_steps` and `_plan_step_idx` untouched,
`_planner_script` kept, `_script_idle_run` reset to 0, the log names "no active
goal", and "unfinished" is absent. That is my driven result, asserted.

Mutant — deleting the callee guard at `agent.py:3856-3859`:

    FAIL: test_the_yield_refuses_a_goal_less_bot_at_its_own_seam
    Ran 115 tests / FAILED (failures=1)

Exactly one red, at its own name, 115 run. Their claim reproduces. Restored,
`cmp` clean, `git status --porcelain` empty. Suite: `Ran 165 / OK`, `rc=0`,
unpiped (164 + 1).

## Where their test is stronger than my evidence

My probe reported `idle_run=0` in the goal-less case, but I set the counter to
zero implicitly — so "reset to 0" and "never touched" were the same observation
for me. Their test sets `_script_idle_run = 3` first, then asserts 0. That
distinguishes a **reset** from a no-op, which my evidence could not. The callee
does reset (`agent.py:3858`), so the stronger assertion passes. Worth saying
plainly: the test they wrote is not a transcription of mine, it is a better one.

## The spec sentence

    The refusal MUST live in the yield itself, not only at the idle caller. …

It states the reason, not just the rule — one predicate at the callee covers all
three callers so they cannot disagree. That is the actual invariant and it is
the one that would rot if someone later moved the guard to a caller. `openspec
validate script-lookups-and-results --strict` → valid, `rc=0`.

## Their process note, checked

They reported nearly splicing this test into the adjacent goal-less test and
silently dropping its last two assertions, catching it only because the new test
failed on an assertion they had not written. I checked the committed arrangement:
the diff is a pure insertion (`@@ -462,6 +462,35 @@`), the adjacent test's
`assertNotIn("while its goal was unfinished", …)` and
`assertNotIn("not yielding", …)` are both intact above the insertion point. The
committed file is correct.

That failure mode — a green suite hiding dropped assertions — is worth naming
generally: a spliced test body can remove coverage without changing a single
result, because the missing assertions were the ones that would have failed.

## Not established

Unchanged from the parent review: no live bot; trial 4.2's retry and 4.3's open
end still need a server. The NC-1 follow-up I filed at `29a7a38` stands on its
own row and is not addressed by this commit.

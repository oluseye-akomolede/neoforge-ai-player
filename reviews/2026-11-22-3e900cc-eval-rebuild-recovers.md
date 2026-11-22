# 3e900cc: eval rebuild recovers an offered script section — PASS

Rev reviewed: `3e900cc`. Reviewer: minecraft-reviewer@minecraft. 2026-11-22.
Closes F-1 on `c0cfb47`.

## Verdict

PASS. My F-1 was "add a test for the recovery direction"; the fix is better than
what I asked for. I had assumed recovery could be verbatim or empty -- two cases.
The commit shows there are three: present-and-matching, never sent, and
*heading present with wording this build does not hold*. The third cannot be
recovered honestly, because this build does not have the text the model saw.

Folding that third case into `""` is what made my mutant survive: a recorded
prompt from an older rev would have been scored against a prompt without the
section, which is a plausible substitution, not the real input. Raising
`Unscorable` is the correct answer and it is the one the harness already knows
how to handle.

## Verified at the rev

Byte-source: `git archive 3e900cc` into a scratch tree, so my branch stayed put
and every number below is from the reviewed rev.

- `output_evals/tests/test_sysprompt`: **Ran 21, OK, rc=0** (was 17; the
  commit's figure).
- Full agent suite, `AGENT_SCRIPT_RUNNER` set: **Ran 641, errors=1, skipped=1**
  -- exactly the commit's figure. The one error is `dashboard`
  (`ImportError`, missing uvicorn), pre-existing and unchanged.
- `openspec validate coded-agents --strict`: **rc=0** unpiped.

## Mutants — both claims reproduce

- **Mutant C** (body replaced with `return ""`, my own mutant): reds exactly 3 of
  the 4 new tests and leaves `test_a_recorded_absence_stays_empty` green. That
  green is the point: the absence case was already covered, which is why my
  mutant survived before.
- **Mutant D** (`raise` disabled): reds `test_another_builds_section_is_unscorable_not_empty`
  alone.
- Both applied behind an `assert old in s` guard and syntax-checked before the
  run, so a no-op mutant could not read as survival. Restored `cmp`-identical.

## What I checked beyond the claims

- **The heading is the section's own first line.** `_PLAN_SCRIPT_SECTION`
  starts with `_SCRIPT_HEADING` exactly, so `section in text` implies
  `heading in text` and the two branches cannot misorder. The `and section`
  conjunct is defensive only -- `_PLAN_SCRIPT_SECTION` is a non-empty module
  constant at `l3_planner.py:290`, so a planner with an empty section is not
  reachable. Probed: a no-section planner with the heading present returns `""`
  without raising, which is the correct answer for an unreachable case.
- **The raise joins an existing mechanism, it does not invent one.** Nine other
  sites in `sysprompt.py` raise `Unscorable`, and `output_evals/run.py:507`
  catches it, sets `prompt_differs/prompt_diff`, and counts the case under
  `unscorable` -- excluded from scoring rather than scored as blank. An
  uncaught raise would have been the real defect here; there isn't one.
- **The spec pins all three cases** and each is tested by name. The third
  scenario's `- AND the reason MUST say the recorded prompt offered scripts`
  is asserted (`assertIn("offered scripts", ...)`).

## Not established

No live bot. This is eval-harness code and does not touch the bot loop.

## Note on my own instrument

I extracted with `git archive` and ran the full suite there; 30 tests went red.
That was mine, not theirs: the scratch tree had no `AGENT_SCRIPT_RUNNER`, and
these tests refuse to skip -- `test skipped instead of running: agent-script-runner
not found ... A skip is not evidence; red is the correct outcome`. Setting the
path gave 641, matching the commit. I reported the first number to nobody, but
it is the second time tonight an archived tree has produced a false red and it
is worth stating that a scratch extraction is not a clean environment.

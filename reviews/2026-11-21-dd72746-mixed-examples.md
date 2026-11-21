# Review: dd72746 - mixed-example requirement, dated-choice, option-2 scenarios

Rev: dd72746 (neoforge-ai-player, ship-ca27-harness)
Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-21

## Verdict: PASS ON THE PROSE, FAIL ON THE SCENARIOS. F-1, F-2, F-3.

validate --strict rc=0. Spec-only commit: one file, +30/-8, tasks.md untouched
(which is the cause of F-2 and F-3).

The two paragraphs this commit exists for are good and I would keep them
verbatim. See "What is right" below. The three findings are all the same
mechanism: the scenario bodies were rewritten to describe option 1, and the
task list still specifies option 2.

## F-1 - the stop-being-the-driver scenario no longer tests a consecutive count

Requirement text, unchanged and still binding by the paragraph that follows the
options list:

  The counter MUST be consecutive: a tick that dispatches something resets it,
  so a script that intermittently succeeds is never torn down.

Scenario, after this commit:

  #### Scenario: A script whose only action is refused stops being the driver
  - GIVEN a bound script whose only action is an unknown kind
  - WHEN a tick refuses every action it proposes          <- was: N consecutive ticks
  - THEN the bot is no longer running that script

When N consecutive ticks became one tick, this scenario stopped being
distinguishable from the reset scenario. The reset scenario reads "the refusals
never reach N in a row ... THEN the script stays bound" - and if one refusal
alone stops the script, then "never reach N" for any N >= 2 is satisfied by a
single dispatch, but a script that refuses *once* and dispatches never must now
be BOTH "stays bound" (reset scenario) and "no longer running" (this scenario).

The two scenarios are now jointly inconsistent, not merely out of date. The
minimal fix is to put the count back in the WHEN, or to keep one tick and make
the reset scenario say what resets it. I do not mind which; I do mind that the
requirement body says consecutive and no scenario tests it.

## F-2 - task 2a.14 still specifies option 2, including "chat"

tasks.md:211-226, unchanged by this commit:

  Implement option 1 (yield the goal ...) with a consecutive-tick counter, and
  log which option fired. Verified by: a script whose only action is an unknown
  kind stops being the driver within N ticks, the reason is in chat and the log

Three things in that one task now contradict the spec:

 1. "within N ticks" - the spec's option 1 has no N. N is defined in option 2
    ("After N consecutive all-refused ticks"). The body then says option 1 is
    the shipped behaviour and N "is not fixed by this requirement". A test
    written from 2a.14 will assert an N that the requirement says does not
    exist for option 1.
 2. "with a consecutive-tick counter" - option 1 as written needs no counter.
    Unbinding on the first all-refused tick is unconditional. The counter, and
    "a tick that dispatches something resets it", are the machinery of option 2.
    If the intent is that option 1 also uses a counter, the requirement must say
    so; F-1 is the same gap seen from the scenario side.
 3. "in chat and the log" - the requirement's option 1 says only "in the log",
    and the scenario says only "in the log". The spec was changed away from chat
    deliberately (it is visible in the diff) and 2a.14 was not.

F-2 is the one that costs work: an implementer doing 2a.14 test-first will write
three assertions the spec does not support, and the spec is supposed to be what
they implement against.

## F-3 - "PASS ON THE PROSE" is not "keep the odd scenario bullet out"

Minor, same family. The scenario now has

  - WHEN a tick refuses every action it proposes

with no count, while the paragraph two above it explains at length that N MUST
be a single named constant. A reader landing on the scenario first sees a
counter-free rule and a constant it never uses. That is F-1's root cause stated
as a readability problem; fixing F-1 fixes it.

## What is right, and worth saying plainly

- **The mixed-list paragraph is the correct generalisation of my finding.** I
  reported that two of four examples bind and said that is worse than an
  all-wrong list because it looks intermittent. The commit states that as the
  reason the bug survived a trial, which is the right causal claim, and draws
  the right test obligation from it: "the test MUST cover each one rather than
  asserting membership of the list as a whole." A test asserting the list is a
  subset of BINDABLE_KINDS passes today when half the list is missing; per-item
  coverage does not. That is exactly the distinction the requirement needed.
- **The dated-choice rewrite is right.** "For 2026-11-21 this requirement is
  satisfied by option 1" did read as though it might expire. "Option 1 is the
  shipped behaviour for this change ... Option 2 remains the stated alternative"
  records the choice without a date and without forbidding the future. This is
  the note I raised and it is closed properly.
- **The N paragraph names the measured number and its consequence.** 69
  refusals, so any N below about 30 would have fired. It also requires "a single
  named constant rather than a literal at the comparison" and "the
  implementation MUST record the observation that chose it", which is the right
  shape: it constrains the form while leaving the value to whoever has the tick
  length.
- The `remove chat from the scenario` change is defensible on its own: option 2
  explicitly carries chat, option 1 as described is an internal yield, and the
  requirement keeps "the implementation MUST state which in the log". F-2 is
  only that the task list was not brought along.

## Checked, not assumed

- validate --strict on ai-written-scripts: rc=0.
- Commit touches exactly one file (spec.md); tasks.md is byte-identical to
  f7b31c4, which is why F-2 and F-3 exist in an otherwise careful commit.
- Both scenario names are present at dd72746 and neither was dropped - this is
  a MODIFIED-delta question I checked by header first, and the file is an
  amendment to an existing requirement, so no scenario is lost by rename.
- The 69-refusal figure matches what I verified at f7b31c4 against agent.py.

## Not verified

The claim "0 new plans over six minutes" is a trial observation I did not
re-run; it is consistent with the code path I traced at f7b31c4 (nothing clears
_plan_steps on the refusal path, so _check_task_board is skipped) and I am
treating it as a record, not as a measurement of mine.

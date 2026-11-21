# Review: ddf7ebb - option-1 ownership, counter made option-2 only, 2a.14 rewritten

Rev: ddf7ebb (neoforge-ai-player, ship-ca27-harness)
Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-21

## Verdict: PASS. F-1, F-2, F-3 from dd72746 all closed. One new minor F-4.

validate --strict rc=0, run at ddf7ebb. Two files: spec.md +53/-25, tasks.md
+17; both moved this time, which was the whole cause of the previous round.

## F-1 closed, and closed better than I asked

dd72746's contradiction was that the requirement body demanded a consecutive
counter while the stop-being-the-driver scenario fired on a single tick. I
offered two fixes: put the count back in the WHEN, or keep one tick and rewrite
the reset scenario. The commit did the second, and did it as an ownership split
rather than a wording patch:

  - Option 1 now says outright "This option needs no counter: an all-refused
    tick is not a thing to wait out, it is a script that cannot dispatch."
  - The consecutive-counter rule moved INTO option 2's paragraph, so it is
    scoped to the option that needs it instead of floating as a global MUST.
  - The old "A tick that dispatches resets the refusal count" scenario was
    replaced by "A tick that dispatches one action is not all-refused (option 1)",
    which tests the property option 1 actually has: partial dispatch keeps the
    script bound because the tick did not refuse *every* action.
  - A separate scenario, "Serialising to option 2 replaces the counter
    behaviour", carries the postponed semantics and says in a NOTE that it
    applies only to option 2.

That is the right structure. It removes the contradiction at the source instead
of making two scenarios agree by accident, and it means a future implementer
choosing option 2 has the counter's semantics written down rather than
reconstructing them from a deleted scenario.

## F-2 closed

tasks.md 2a.14 rewritten. Re-read against the spec:

  - "within N ticks"            -> gone; now "on its first all-refused tick"
  - "with a consecutive-tick counter" -> gone; now "Option 1 has no N and no
    counter -- do not add one, and do not wait for a streak"
  - "the reason is in chat and the log" -> now "in the log"
  - new verification: "a script that refuses one kind but dispatches another on
    the same tick STAYS bound, because that tick did not refuse every action"

That last clause is the one I would have asked for: it is the boundary that
distinguishes option 1's rule from a naive "any refusal unbinds". It matches the
new scenario exactly.

Checked mechanically: `grep 'within N\|chat and the log'` over tasks 2a.14
returns only the sentence that says there is no counter -- i.e. the old phrases
survive as a negation, not as a stale requirement.

## F-3 closed

The scenario no longer sits below a body demanding an N it does not use; the N
discussion is now explicitly conditional ("Under option 1 there is no N and no
counter"). Nothing to fix.

## F-4 (new, minor) - the option-2 scenario's AND clause cannot fire under its own WHEN

  - **WHEN** the script refuses every action for fewer than `N` consecutive ticks
    and dispatches on each intervening tick
  - **THEN** the script stays bound
  - **AND** once `N` consecutive all-refused ticks occur it is unbound

The WHEN pins "dispatches on each intervening tick", so by construction no two
all-refused ticks are ever consecutive. I walked it: for N = 3, 5 and 30, the
longest all-refused run the WHEN admits is 0. The AND therefore describes a
condition its own GIVEN/WHEN forbid.

This is not unsatisfiable - the THEN states a counterfactual and the scenario is
readable - but a test written from it can only assert "stays bound". The
unbind-at-N half is unexercised by the scenario that names the behaviour. Fix is
one sentence: split it into two scenarios, or drop "and dispatches on each
intervening tick" from the WHEN and let the second half of the sequence occur
after the first clause has been observed.

Severity: low. Option 2 is not the shipped behaviour, so nothing implements this
today. But it is the only written spec of option 2's semantics, and the one
clause that matters - that N consecutive refusals unbind - is the clause a naive
test will skip.

## Checked, not assumed

- validate --strict at ddf7ebb: "Change 'ai-written-scripts' is valid", rc=0.
- Scenario census: 3 scenarios under this requirement (stop-being-driver,
  not-all-refused, serialise-to-option-2). No duplicate scenario names anywhere
  in the spec file.
- `resets the refusal count` no longer appears anywhere in the change: the old
  scenario was renamed, not duplicated, so nothing was silently kept alongside
  its replacement.
- The sibling scenario at :965 ("A refused kind reaches the fallback, not a
  stall", a different requirement) still reads consistently with option 1: one
  all-refused tick, unbind, hand back, reason in the log. No change needed there
  and none made.
- The `attack`/`place` requirement this change also carries is unaffected by this
  commit and still matches what I verified at f7b31c4.

## Not verified

Nothing code-side; this is spec text only and I ran no suites. The trial figures
(69 refusals, six minutes) are unchanged from dd72746 and were checked there.

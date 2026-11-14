# Review of 8e5c7f5 — None-vs-0 pinned by assertion

Reviewer: minecraft-reviewer@minecraft, 11-14 00:44Z.
Read from `git archive 8e5c7f5`. Parent 509c5a8.

## Verdict: PASS

## What was asked

My 509c5a8 residual: `single_directive_rate` being `None` when unmeasured was
proven only by consequence (a wrong implementation divided by zero), not by
assertion. A refactor returning some sentinel such as `-1.0` would have stayed
green.

## Verified by running their mutants myself

Suite at 8e5c7f5: **86 tests, OK**.

| mutant | reddens | message |
|---|---|---|
| rate coerced to `str` | `test_single_directive_adherence_is_reported` | `'0.0' != 0.0` |
| unmeasured branch returns `-1.0` | `test_unscorable_only_kind_reports_no_adherence_rate` | `-1.0 is not None` |

Neither reddens the other. I checked that directly rather than reading the
claim: mutant A leaves the unmeasured test green and mutant B leaves the
measured test green, so the two assertions cover disjoint properties. That is
the property that makes the pair worth having -- one assertion could not have
caught a sentinel that was still a float.

Assertions at `test_run.py:252` (`assertIsNone`), `:327` (`== 0.0 `) and `:335`
(`assertIs(type(...), float)`). Mutant A's message is produced by the `:335`
type pin, not the `:327` value pin, which is why the str case needed its own
line.

## Not in dispute

The `AREA_LOOT` scope decision is right and I am not asking for a change: the
mod accepts `SKILL` with no explicit directive entry, whereas `AREA_LOOT` would
carry x/y/z coordinates the binder drops, so failing it is correct until the
binder gap is fixed as the separate finding. Folding that into this change would
change what the eval measures mid-flight.

## Nothing outstanding from me on agent-output-evals

All findings from my four rounds are closed: the inventory gap (F1), the
`/api/tags` probe (F2), the untested-gateway task (F3), the eval-runner think key
(N1), and this residual. No image, no rollout.

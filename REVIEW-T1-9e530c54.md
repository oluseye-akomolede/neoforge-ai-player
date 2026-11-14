# Review: T1 order-dependence fix — PASS at `9e530c54`

Rev: `9e530c54` (`9e530c5`), neoforge-ai-player, branch `minecraft-wt-deepseek`.
Reviewed from `git archive 9e530c54` in a fresh scratch dir, not from any working tree.
Supersedes my NOT PASS at `cf9a37a` on `38b8721`.

## Verdict

**PASS.** T1 is closed. The fix removes the property's dependence on import
state rather than defending it, which is the option I recommended and the
stronger of the two.

## What I ran, on the archive of `9e530c54`

| Invocation | Result |
|---|---|
| `discover -s agent/output_evals/tests -t .` | **96 OK** |
| `discover -s agent/output_evals/tests` (no `-t`) | **96 OK** |
| single module `test_run` from the tests dir | **19 OK** |

At `38b8721` the `-t .` invocation failed on
`ScorerSurfaceTests.test_an_unloadable_action_surface_is_refused`. It now passes.

## The fix is not vacuous — measured, not read

I did not take the builder's mutation claim on trust. Three mutations, run in a
copy of the same archive:

1. **`return True` before the registry check** — reddens **2** tests
   (`test_a_registry_missing_a_kind_is_refused` and the surface test).
2. **`return True` directly before `surface, err = planner._load_surface()`** —
   reddens **exactly 1**: `test_an_unloadable_action_surface_is_refused`. This is
   the builder's described mutant, and their "exactly that one test" is precise.
   My first attempt (1) was broader than their claim and is not evidence against it.
3. **Replacing the stub's `assertTrue(_SwallowedFailure.SCORERS, ...)` with
   `assertTrue(False, ...)`** — reddens the same single test, so the trap
   assertion is load-bearing alongside the refusal assertion.

Under mutation 2 the failure text is `True is not false : an unloadable surface
must be refused` — the right assertion on the right property, not an incidental
crash.

## Why the fix is right, beyond making this test green

The test now injects a `planner_module` stub and touches no import state at all.
That matters because of what I could not establish at `38b8721`: I measured that
`_load_surface`'s import *succeeded inside a `sys.modules` block that set those
names to `None`*, and that `run.planner is planner` with one planner module and a
clean cache going in — and I could not isolate the mechanism across four
reproductions. The fix does not require me to understand that mechanism, because
the property under test ("the precheck refuses when the surface reports an
error") is now stated directly rather than staged through global import state.
That is the correct response to an unreproducible staging artefact.

The stub keeps `SCORERS = dict(planner.SCORERS)` populated, so the trap the test
exists for — an import-only check passing while the surface is broken — is still
represented, and asserted alongside the refusal.

## Production path unchanged

`run.py:280` calls `precheck_scorers()` with no argument, so the injectable
parameter is test-only. The real planner is still imported and checked in the
Job. No default was quietly narrowed.

## Note carried forward, not a finding

The builder withdrew the `38b8721` commit message's order-independence claim,
which is the right correction. `38b8721` remains NOT PASS. The image built from
it is not rebuilt from this rev by me — that is the builder's call and the
deploy record's, not this review's.

## Self-correction log

- I first ran the suite in an unmutated copy while reading a mutant's path, then
  re-ran in the mutated dir. The two-confusion cost one round trip; the archived
  result above is from the dir the mutation was verified present in.
- I reproduced T1's failure four times in isolation and never in the runner. This
  review states that boundary rather than claiming a root cause.

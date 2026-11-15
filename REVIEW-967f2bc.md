# Review 967f2bc — job passes --rebuild-from-source; fail-closed on empty prompt

**Verdict: PASS on the two fixes. One NEW BLOCKER found in make-evals-configmap.sh's
kubectl branch (F5), which must be fixed before anyone applies from controlplane.**

## The lead's blocker is fixed, and my earlier PASS missed it

The lead was right and I was wrong to pass 9ad6930 on this point. I verified the
rebuild *runs* at run.py:341; I did not verify the Job *passes the flag that
reaches it*. A flag that never arrives makes that code dead. That is a gap in how
I scoped the check, not a subtlety: "the code path exists" and "the code path is
entered" are different claims and I made the first while reporting the second.

Fixed and verified by parsing the YAML, not reading the diff:

- `--rebuild-from-source` is present in the parsed container args.
- Volumes mount where the code reads: evals-scout-cases -> /opt/cases/exec
  (exec.jsonl only), evals-scout-cases-rebuild -> /opt/cases/rebuild
  (plan.jsonl + replan.jsonl). read_cases_dir rglobs /opt/cases, finds both.
- Names match the builder's statement: evals-scout-cases, evals-scout-cases-rebuild,
  evals-code-before/after.

## Fail-closed guard verified by driving it

- Direct: a deferred plan case (recorded set, prompt empty, rebuild_applied=False)
  raises EmptyPrompt with the informative message.
- Mutation: disabling the guard (`if False:`) reddens exactly
  test_without_the_flag_the_run_fails_closed. The guard is pinned.
- The test is not vacuous: it stubs the endpoint, avoids --dry-run, asserts rc=5,
  asserts sent.call_args is None, and asserts no report file. That is a real
  fail-closed assertion in both directions.
- Exit path: returns 5 before any report write; reason on stderr.

## F2 from 3708de0/9ad6930 is CLOSED

Re-applied my exact mutant (return at the first }) — 17 tests, 2 ERRORS:
test_a_brace_inside_a_criteria_does_not_truncate_the_plan and
test_balanced_object_counts_braces_inside_strings. Both purpose-named, one
driving _balanced_object directly and one rebuilding a real case with
"chest has {16} wheat". Exactly the fixtures asked for.

## F5 (NEW, BLOCKER) — make-evals-configmap.sh's kubectl branch builds the wrong ConfigMaps

Lines 142-145, the `if command -v kubectl` branch:

    kubectl create configmap "$NAME" --from-file="$OUT/cases" ...

Two defects, both invisible on this VM because kubectl is absent and the else
branch runs instead:

1. **It creates one ConfigMap from the whole $OUT/cases directory**, which holds
   exec.jsonl, plan.jsonl AND replan.jsonl (`--cases-out "$OUT/cases"` writes all
   three). That single map is the unsplit set: 1312167 B encoded, 263591 over the
   cap. The guard at check_cm correctly refuses that shape, but this branch builds
   it AFTER the guard passed (the guard checks the split, not a directory-wide
   create), so the apply is rejected by the API server after the script printed
   success.
2. **It never creates $REBUILD_NAME.** Only $NAME is created. The Job mounts
   evals-scout-cases-rebuild, so it starts with a missing volume.

The else branch (lines 157-159) is correct: explicit --from-file=exec.jsonl=...
and a separate $REBUILD_NAME. So the bug fires exactly where the lead would apply
from - a machine with kubectl, i.e. controlplane.

Fix: make the kubectl branch mirror the else branch's two creates, with explicit
--from-file keys.

## Minor

The comment at the top of the script still describes the split correctly. No action.

## Not verified

I have not run the Job. Endpoint probing on this VM returned an empty /api/tags
with rc=0, which is not a usable instrument, so I did not build a live-scoring
check on it.

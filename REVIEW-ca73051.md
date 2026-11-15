# Review ca73051 — delete the kubectl branch; check apply-matches-Job

**Verdict: PASS. F5 is closed, and by the right fix. One residual (F6) on the new
check's scope, not a blocker.**

## F5 closed

The kubectl branch is gone. The script now prints one shape, and that shape is
correct: three creates, explicit --from-file keys, and the split matches the
guard (exec alone; plan+replan together). Deleting beat mirroring -- my
suggestion was to mirror, which would have left two paths free to drift again.

Verified from the file at ca73051, not the diff.

## The check works in both directions on REAL edits

Ran evals/check_apply_matches_job.py: rc=0 on ca73051; parses 3 Job volumes and
3 created names, all matching.

Then attacked it rather than trusting the two outcomes the builder reported:

- M1 drop the REBUILD create line -> rc=1, "the Job mounts ConfigMaps nothing
  creates: evals-scout-cases-rebuild". Correct.
- M2 Job mounts a 4th volume nothing creates -> rc=1, names evals-ghost. Correct.
- M3 (the interesting one) the create line still present as text but rendered
  inert -- `# DISABLED: kubectl create configmap $REBUILD_NAME ...` inside the
  echo -> **rc=0, passes.** The check reads text, not execution. A commented-out
  create satisfies it.
- M4 --from-file repointed at the wrong file (plan.jsonl sourced from exec.jsonl,
  replan.jsonl sourced from plan.jsonl) -> **rc=0, passes.** The key names are
  right; the BYTES are the wrong kind.

M3/M4 are the same failure this whole row has been about, one level up: the
check confirms the NAMES agree and never confirms the named thing is what gets
created, or that the line creates anything at all. It closes F5 (name drift) and
does not claim to close content drift; it should say so in its docstring, or
parse `--from-file=<key>=<src>` and tie the source suffix to the key.

I put this as F6 rather than a NOT PASS because:
 - the defect F5 is genuinely closed,
 - the printed commands are correct as written today,
 - and the residual is a false-negative mode in a guard, not a live defect.
But it is the same class as the two the builder found by running instead of
reading, so it should not be left implicit.

## Suites

113 evals tests, 10 prompt tests, 43 agent tests -- all OK, run per-module and
counted by the runner's own "Ran N" line.

On my counting: my first pass reported 101 evals tests because I ran each file as
`python3 <file>`, which executes fewer tests than unittest collects. The builder's
113 is correct and mine was the instrument. Fourth time this session; same shape
every time -- reporting a total without asking the runner for its tally.

## Still unproven (agreed)

Nothing here proves controlplane's kubectl accepts the printed commands. The
argued claim is the narrow one: Job volumes and printed creates name the same
three ConfigMaps. That is the thing that drifted, and it is now checked.

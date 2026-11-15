# REVIEW 16064a8 — wire the decline labels, restore "where", fix a self-contradicting example

Reviewer: minecraft-reviewer. Reviewed from `git archive 16064a8`, not the builder's worktree.

## Verdict

**PASS for merge.** One small hole in the new guard, filed as H1 below; it does
not block this commit and I would fold it into whatever touches that file next.

## What I verified, and how

**The wiring works, all the way to the process that runs.** This was the finding
in `2fa735b`, and the fix is real rather than nominal:
- `evals/job-evals.yaml` passes `--decline-labels /opt/evals/output_evals/case_labels.json`;
  `run.py:434` parses it, `run.py:595` passes it into `run()`, `run.py:138` defaults
  it, `run.py:226` consumes it per case. Read at the rev in one pass, not inferred.
- **The bundle does NOT carry the file — see H2.** The tar the Job extracts has
  12 members and no `case_labels.json`, so this path does not exist in the pod.
  The new guard does not catch it: it checks flags, not paths.

**The guard reddens on real removals.** Mutation-tested against the committed tree:
| mutant | rc |
|---|---|
| baseline (unmutated) | 0 |
| `--decline-labels` typo'd to `--declin-labels` | 1, names the flag |
| `--rebuild-from-source` commented out | 1, names the flag and the consequence |
| a flag reachable only as a YAML comment | 0 (correctly ignored — see below) |

**The prompt fix is substantively what I proposed, and the extra catch is real.**
The clarify now reads "whose things, and where they are". The builder also found
that the closing example still said `"put MY things in the chest" → get the things`,
which was the same ownership defect surviving in the summary sentence. That was a
genuine find, not a drive-by: it is the sentence a model is most likely to pattern-match,
and it contradicted the ownership rule two paragraphs above it. Mutants all killed —
restoring the MY-things example, dropping the "where" half, deleting the substitution
rule, turning clarify into gather, and swapping the YOURS example back to MY.

**The labels are right, and `187451a0` now carries the reading I asked for.**
`verdict: plan`, `alt_verdict: clarify`, `why` states both. Rejecting `refuse` as an
alternative in the loader is the correct call: refusing is the defect being counted,
so it cannot also be a correct answer to the same ask.

## H1 — the guard's "unknown flag" direction is a substring test, not a parse test

`check_apply_matches_job.py` decides a Job flag is known with
`f'"{a}"' not in run_py`. That searches the whole of `run.py` for the quoted
string, so it is satisfied by a flag that appears anywhere — a comment, a docstring,
a message — and not only by one `argparse` parses.

I demonstrated it: rename the `add_argument('--decline-labels')` call to
`'--decline-labelz'` and leave the old literal in a comment, and the guard still
returns 0, while the Job would fail in the pod with "unrecognized arguments".

This is the same failure shape as F7 on the harness row: a check that reads prose
where it means to read code. The fix is one line — collect the parsed set with
`set(re.findall(r'add_argument\("(--[A-Za-z0-9-]+)"', run_py))` and test
membership — and it makes the check's stated intent ("one `run.py` actually
parses") true rather than approximate. The "missing required flag" direction is
sound and does not need changing.

Severity: low. It cannot pass a run that would fail — a false pass here means
the guard stays quiet while a typo ships, which is exactly what it was built to
prevent, but the required-flag half still catches both historical misses.

## H2 — `case_labels.json` never reaches `code.tar`

- `make-evals-configmap.sh:88`: `cp agent/output_evals/*.py "$OUT/code/output_evals/"`
- `make-evals-configmap.sh:89`: scorers glob
- `make-evals-configmap.sh:104`: `cp agent/l3_planner.py agent/plan_schema.py …`
- `make-evals-configmap.sh:138`: `tar cf code.tar output_evals` — tars only what
  the staging dir already holds.

`case_labels.json` matches none of those patterns. The Job will pass
`--decline-labels /opt/evals/output_evals/case_labels.json` to a path that does not
exist in the pod, and `load_decline_labels` returns `{}` for an absent file — by
design, since an unlabelled run is the honest default. So the run reports
`decline_cases n=0` and looks exactly like the run this commit was supposed to fix.

This does not block merge — the commit is correct on its own terms and the glob is
in a different file — but it **must be fixed before the after-leg**, or the lead's
rerun will reproduce the original symptom and it will look like the label data was
wrong rather than absent.

## Suites run at this rev

122 eval tests, 15 planner-prompt tests, `check_apply_matches_job.py` rc=0 on the
committed tree. Ran from a clean `git archive`, not the worktree.

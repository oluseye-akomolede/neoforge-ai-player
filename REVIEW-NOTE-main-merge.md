# Note: the 807b6f1 / fee4e53 pin edit — no conflict, superseded

**Written 11-16 10:2xZ, in reply to the lead's merge of `ship-ca27-harness` into `main` as `4e47b41`.**

## What I said (441d08b) and what is true

In `441d08b` I warned that `807b6f1` and `fee4e53` edit `evals/job-evals.yaml:62` and
`:89` independently from the same base, and that a merge of both branches would
conflict there — with the risk that a blanket `--ours` would silently revert the
pin to `a9e75ad1`.

The ancestry claim was correct. The merge-risk conclusion was not.

Verified at `main` = `4e47b41`:

- `git merge-base --is-ancestor 807b6f1 main` -> NO (as I said)
- `git diff 807b6f1 main -- evals/check_apply_matches_job.py evals/make-evals-configmap.sh` -> empty
- `main:evals/job-evals.yaml:62` and `:89` -> `2914fb85ff22`
- distinct digests across `main -- evals/` -> exactly one, count 2

So `fee4e53` already carries the same harness content that `807b6f1` carries. There is
no second side to conflict with, because only `ship-ca27-harness` was merged.

## The residual risk, stated correctly

The conflict would only arise if someone merged the `minecraft-wt-deepseek` reviewer
branch whole. That branch is superseded and the lead has ruled it out. **Flag it if
anyone proposes merging that branch.**

## The part that still stands

Resolve a pin conflict on `job-evals.yaml:62`/`:89` by reading the value, not by
taking a side: it is the field whose drift already cost a run, and both sides
happening to want the same value makes a wrong resolution indistinguishable from a
right one at the level of merge output.

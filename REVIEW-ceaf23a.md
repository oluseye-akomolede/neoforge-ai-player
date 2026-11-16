# REVIEW ceaf23a — H2 fixed and guarded; H1 is not fixed

Reviewed from `git archive ceaf23a`, clean room, guard and script taken from the rev.

## H2 — closed

- `make-evals-configmap.sh` now has `cp agent/output_evals/case_labels.json`.
  I ran the staging lines on a tree holding the file: the tar carries
  `case_labels.json` and extraction produces `/opt/evals/output_evals/case_labels.json`,
  which is the path the Job passes.
- The new staging guard reddens on all three shapes I tried: `cp` deleted (rc=1),
  `cp` commented out (rc=1), `cp` replaced by `*.json` glob (rc=1). Each names
  the missing file. It also returns 2 when its own regex finds no `cp ... $OUT/code`
  lines, which is the right failure for an empty match.

## H1 — NOT fixed. The guard still cannot tell a declaration from a comment

`check_apply_matches_job.py:166`:

```python
declared = set(re.findall(r'add_argument\(\s*"(--[A-Za-z0-9-]+)"', run_py))
```

The pattern has no anchor and no exclusion for `#`, so a commented-out
declaration is counted exactly like a live one. Confirmed by execution on the
clean archive: commenting out
`ap.add_argument("--decline-labels", default=None,` and leaving the rest of the
call intact leaves the guard at **rc=0**, while the pod would reject the flag.

The builder's stated mutant (rename the flag, leave the old literal in a
comment) does pass, because a rename removes `add_argument(` from the line. That
mutant tests the rename, not the comment. The property the guard claims — "one
`run.py` actually parses" — needs the parse, not a pattern.

Proposed fix, two lines:

```python
live = "\n".join(l for l in run_py.splitlines() if not l.lstrip().startswith("#"))
declared = set(re.findall(r'\badd_argument\(\s*"(--[A-Za-z0-9-]+)"', live))
```

## Process note — this cost me several rounds, and the reviewer is partly at fault

My first runs of this mutant reported rc=0 and I twice wrote it off as my own
harness, because two earlier attempts in this session were exactly that. Both
were true at different moments: an intermediate fixture had a stale `run.py`, so
some of the rc=0 readings were genuine harness noise. The conclusion held
anyway, but I got there by repetition rather than by isolating the variable.
The lesson is the one already in my notes: print the mutated line and run the
guard's own regex before concluding, rather than inferring from rc.

## Everything else in the commit

The comment fixes to `load_decline_labels` and the `187451a0` labelling are
carried over unchanged from `16064a8` and were reviewed there.

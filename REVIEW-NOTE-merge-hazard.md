# Supersedes REVIEW-NOTE-main-merge.md: the merge hazard is the spec, not job-evals.yaml

**11-16, after a dry merge of `807b6f1` into `bb1d445`. This note replaces my
`:62/:89` warning, which was wrong in both directions.**

## Measured

`git merge-base 807b6f1 bb1d445` = `ca27b6e`.

| File | Dry-merge result |
|---|---|
| `evals/job-evals.yaml` | **no conflict** — `git diff 807b6f1 bb1d445 -- evals/job-evals.yaml` is empty; both sides already identical |
| `openspec/changes/planner-prompt-declines/specs/l3-spec-driven-planning/spec.md` | **CONFLICT (content)**, reported by `git merge-tree --write-tree` |

## Why the spec conflict is the dangerous one

`807b6f1`'s copy of the spec is byte-identical to `1885d4c`'s — sha256 prefix
`664fdc9176ca` on both. `1885d4c` is the rev my review `9be33a9` marked **NOT PASS**:
its delta claims prompt rules (`precondition`, `Planning around`, `by category`,
`ALWAYS preconditions`) that `ca27b6e`'s shipped prompt does not contain.

`bb1d445` is the fix for exactly that. So the conflict does not offer two spellings of
one pin — it offers **the rejected delta against the accepted one**, and taking the
`807b6f1` side reinstates the defect that `af10e5b` passed only once it was gone.

A take-one-side resolution here silently undoes a review. A pin revert would at least
have been visible in a run.

## Withdrawn

My earlier note said `job-evals.yaml:62`/`:89` would conflict. It does not: the files
are identical on both sides. The ancestry half of that note was right; this half was not.

## What to do

The `minecraft-wt-deepseek` reviewer branch is superseded — the lead merges
`ship-ca27-harness` only, and did (`4e47b41`). **Do not merge that branch whole.** If
anything ever does, resolve the spec file by reading it against `ca27b6e`'s prompt, not
by taking either side.

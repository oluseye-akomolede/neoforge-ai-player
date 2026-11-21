# Review: 57dd91b — phantom rev b9edb63 replaced with a81d5d19

Rev: 57dd91b (neoforge-ai-player, ship-ca27-harness)
Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-21
Related: 6bceb29 (review b015576); F-4 filed there.

## Verdict: PASS

F-4 is closed. Three files, one line each, exactly the three sites I named.

## Verified

**The phantom sha is gone from the whole repo, not just the three sites.**

  $ grep -rn "b9edb63" . --exclude-dir=.git --exclude-dir=node_modules
  (no matches, rc=1)

  positive control, same sweep:
  $ grep -rn "a81d5d19" . ...   -> 8 hits across tasks.md, spec.md,
  deploy/agent-scripts.yaml, test_snapshot.py, scout.js

A whole-tree sweep with a positive control in the same batch, because a zero
from a name grep is a claim about the query first. The control returned 8, so
the instrument is live and the absence is real.

**The cited rev now resolves from this branch.** `git cat-file -t a81d5d19`
-> commit, and `git merge-base --is-ancestor a81d5d19 57dd91b` -> true. This is
the part that makes the comment usable: before, a reader hit a fatal; now the
sha they are told to look at is reachable from the branch they are reading.

**The ConfigMap matches the source.** Parsed the yaml, compared `data["scout.js"]`
to `agent/scripts/scout.js` byte-for-byte: identical. So the correction reached
both copies, which was the failure mode I was worried about — fixing scout.js and
leaving the shipped ConfigMap still naming the phantom rev.

**The drift gate is not inert.** Suites are green (`Ran 53, OK`;
`test_scripts_configmap` 2 tests, OK), but a green gate proves nothing on its
own. I mutated one character in the yaml only (`read became` -> `read went`) and
`test_configmap_matches_the_script` went red: `FAILED (failures=1)`. Restored,
`sha256sum -c` OK on both files, tree clean, suite back to OK.

## Not re-verified

The prose claims of the two spec files, which are unchanged by this commit and
which I reviewed at 15b7d7f (a709d51) and 6bceb29 (b015576). Nothing in 57dd91b
touches them.

## Note

Three copies of the same sentence (script, ConfigMap, and to a lesser extent the
test docstring) is why the phantom survived one round of review: fixing any one
leaves the others. The drift test now binds the first two together, so that
particular half cannot recur. The test docstring has no such binding, but it is
prose about history rather than an executable path, so a future divergence there
would be cosmetic.

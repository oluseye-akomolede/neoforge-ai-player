# Review — evals 2.5 fixes at `f60afd5` + Job manifest `eeefdbb`

Reviewer: minecraft-reviewer@minecraft. 2026-11-13 ~17:05Z.
Row: `qitem-20261113162928-37115062c5f6665a`.
**Verdict: PASS.** Both findings from `6380387` are closed and mutation-verified;
the manifest changes are sound and one is verified inside the real image.

Reviewed from `git archive f60afd5` (and `git show eeefdbb:evals/job-evals.yaml`),
not the builder's worktree, at their request and because the tree was dirty through
both commits. All numbers below come from that clean extract.

## Finding A (medium) — CLOSED, mutation-verified

`extract.py:143` now reads
`MIN_PER_KIND - eras.get(self.current_era, {}).get("replayable", 0)`, with the
all-era figure kept beside it as `short_of_30_all_era`. Both are in every kind's
report block, so a reader can always see which pool a number came from.

**The fix is wired into the real path, not just the tests:** `run.py:208` calls
`extract.build_cases(records, current_era=cfg.model)`, so the production run
measures against the configured model.

**The discriminating fixture exists and discriminates.** `test_extract.py:157`
builds 21 current-era + 50 older replan calls — total 71, comfortably over 30 —
and asserts `short_of_30 == 9` while `short_of_30_all_era == 0`. That pair is the
whole point: before the fix the first number was 0, and only a fixture where the
two measures diverge can tell the implementations apart. This one does.

**Mutation, run by me:** replaced line 143's current-era expression with the
all-era one. Result 69 → 67, `FAILED (failures=2)`:
`test_shortfall_is_measured_against_the_current_era_not_all_eras` and
`test_shortfall_without_a_named_era_counts_nothing_as_current`. Restored → 69/69 OK.

**The unknown-era path is safe.** With `current_era=""`, `eras.get("")` is `{}`
and the shortfall reads 30; era keys are never empty (`string(rec.get("model") or
"unknown")` at `:202`), so `""` cannot collide with a real era. More importantly
this state is **unreachable in a real run**: `evalconfig.py:78` requires `model`
as a config key and raises `ConfigError` without it. It is a library-API default,
so "reads 30" is the honest answer rather than a hidden all-era fallback — exactly
what the builder claimed, and I checked the reachability rather than the claim.

## Finding B (low) — CLOSED

`run.py:226` now reads `"no replayable cases: nothing to score (every call lacked
a usable input)"`, matching the `sum(n_cases) == 0` gate at `:228`.

## Manifest `eeefdbb` — the two changes

**YAML anchor for the image: verified to resolve identically.** Parsed the
rendered YAML with PyYAML: `containers[0].image == initContainers[0].image`, both
`...agent@sha256:a9e75ad1...`. One digest, so the unpacker and the scorer cannot
drift apart.

**`python:3.12-slim` → the agent image for the init container: safe, and I checked
it in the image rather than reasoning from the base name.** The init container
needs `tar`; I ran the pinned digest:
`tar` = `/usr/bin/tar`, GNU tar 1.35, and `/usr/bin/sh` present. So the extract
command at `:51` works. (An agent image is a Python image here, but "must be a
Python image" is not "has tar" — the check is cheap and the failure would be a
Job that never starts.)

**No-Secret posture holds.** `automountServiceAccountToken: false` at `:41`, no
`serviceAccountName`, no `secretKeyRef`/`volumes` of Secret type — the pod gets no
API token. Pulling is unaffected: imagePullSecrets are read by the kubelet from
the ServiceAccount, not from the pod token. The builder measured
`kubectl -n ci get sa default -o jsonpath='{.imagePullSecrets}'` →
`[{"name":"harbor-creds"}]`, which closes the one thing I could not check myself
last round.

## What I did not verify

- **The end-to-end rendered run** (75 cases, rc=0; dead endpoint rc=2) is the
  builder's measurement. I did not re-run it against a live endpoint: there is no
  `kubectl` on this VM and the no-exec rule stands.
- **The 1 MiB figures** (25/kind = 960977 B, 30/kind = 1136931 B) come from the
  real corpus, which I cannot read from here. Per-case size is dominated by
  untruncated prompts, so my own synthetic attempt (~1.5 KB/case) is not evidence
  against them — it just does not reproduce them.
- **`n=30` vs the cap** is not a spec violation to resolve: `spec.md:120` says
  "at least **about** 30", so 25 is inside the requirement. Reported to the lead
  as a decision, not a defect.

## Suite

`python3 -m unittest discover -s agent/output_evals/tests -t .` → **Ran 69 tests, OK**,
from the clean extract. Matches the builder's count.

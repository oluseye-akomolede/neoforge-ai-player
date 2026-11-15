# PASS — 6ca3b45 (manifests, base/minecraft/agent.yaml)

Reviewed from a bundle of `refs/heads/pin-agent-digest` into a scratch clone.
Parent `327e708`; against `e41368a` it is one file, +44/-0. Live shapes read
with read-only `kubectl get` via `ssh controlplane`; no Secret values read.

## Verdict

PASS. Test converges on live; prod is live + pullPolicy + three thread vars,
which the lead authorised at 03:47Z as a named, deliberate addition. The commit
message names it as an addition with the reason, which is the condition I asked
for on 03:42Z.

## What I verified

- `git diff e41368a 6ca3b45` contains **zero** `-` lines. Nothing in this range
  deletes configuration from any deployment.
- Live test `.spec.template.spec` matches the file field for field: four env
  values, three mounts with `readOnly` on `scripts`, ConfigMap `agent-scripts`
  with `defaultMode: 420`, `aibot-profiles` emptyDir, `seed-profiles` init at
  `agent:2026-11-05-c193f76` / `IfNotPresent`.
- Live prod env is empty; live `agent-config` (minecraft) has twelve keys, none
  of them OMP/MKL/OPENBLAS. The comment at `agent.yaml:53-57` and the commit
  message both state this correctly.
- Live images are already the digest on both deployments; only `imagePullPolicy`
  was drifting. Matches the commit's scope.
- Prod thread vars sit at `agent.yaml:58-63`, test at `:159-163`, both under an
  explicit `env:` key.

## One operational finding

`minecraft/aibot-agent` uses `strategy: Recreate`. The env hunk
(`@@ -35,11 +35,18 @@`) is an **addition**, not a value change, so the pod
template changes and prod will do a genuine restart on apply. That was already
true for the `Always` -> `IfNotPresent` change, so this costs nothing extra, as
the lead said. Recording it so the rollout is expected rather than reported.

## Self-corrections carried forward

- I reported prod's live image as `agent:latest` from
  `kubectl.kubernetes.io/last-applied-configuration`. That is a record of a past
  apply, not the live spec. The live image was the digest all along; the builder
  caught this and is right. My `containerPort` warning came from the same
  misread and is withdrawn.
- I asserted prod "runs with OMP/MKL/OPENBLAS=1, supplied by agent-config",
  inferred from the file plus `envFrom`. The Secret has no such keys and live
  env is empty. Prod has run with no thread limits at all. That misread is what
  the 03:46Z scope change rested on; the lead reversed it correctly.

## Out of scope, carried

- `evals/job-evals.yaml` pins `a9e75ad1` claiming live is that; live is
  `e80c2e8b`. Needs its own row.
- `test-worlds/pod-template.yaml:139` still `:latest`/`Always`, no live pods.
- Production thread limits were absent until this commit. The user-visible
  symptom, if any, predates it and is not addressed by it.

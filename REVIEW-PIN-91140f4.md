# Review: 91140f4 — pin aibot-agent to the reviewed digest (row qitem-20261115033516-8d8247389179038b)

Reviewer: minecraft-reviewer@minecraft. Date: 2026-11-15. Rev under review:
`91140f4` on branch `minecraft-wt-deepseek` (read via `git show`, not from the
builder's worktree). Row: qitem-20261115033516-8d8247389179038b.

## Verdict

**PASS on the two changed lines. NOT PASS as "both deployments pinned" — the
change as written would move prod off the reviewed image, and it cannot be
applied as instructed.** Four findings below; F2 and F3 are applying hazards,
F1 is a scope gap the builder already disclosed and I confirm.

## What is correct

The image line and the pull policy are exactly as the row asked:

```
-          image: harbor.arcadia-ecs.local/aiplayermod/agent:latest
-          imagePullPolicy: Always
+          image: harbor.arcadia-ecs.local/aiplayermod/agent@sha256:e80c2e8ba8d6aede7062f19eddc780b12277a601f2b91130e3ff7f4e74e2ad3a
+          imagePullPolicy: IfNotPresent
```

`git diff --numstat 91140f4~1 91140f4` = `2 2 deploy/agent-deployment.yaml`, and
`git diff --name-only` names that one file: "exactly 2 lines" holds. The digest is
the one both deployments run, measured at 03:3xZ from the live objects:

- `minecraft/aibot-agent` pod `aibot-agent-7cd57998cb-vcfkt`:
  `imageID = .../agent@sha256:e80c2e8b...ad3a`
- `minecraft-test/aibot-agent-test`: same digest, `imagePullPolicy: Always`

So the diagnosis is right: both last-applied manifests declare `agent:latest`
while both run the reviewed digest.

`IfNotPresent` is right for a digest reference: a restart reuses the pulled
image, and a digest cannot drift under a tag.

`harbor-creds` is declared by the repo manifest and by both live last-applied
manifests, so switching to a digest does not add a new pull requirement. I did
**not** check the Secret exists in each namespace, and my own test-pod pull (or
the running pods' successful digest pulls) is not proof of the same Secret:
`harbor-creds` is a Secret and reading or listing it is off-limits to me under
the lead's rule. That the pods are running the digest today is evidence the pull
works; it is not evidence about a fresh pod after the change. Flagging it as an
unverified assumption rather than dressing it up.

## F1 — (confirmed) no manifest for `aibot-agent-test` exists here

The builder's scope-gap claim is right. At `d49aed9` and at `91140f4`,
`git ls-tree -r --name-only -- deploy/` lists exactly five files and only
`agent-deployment.yaml` is a Deployment. `git grep -l aibot-agent-test` finds
28 files and every one is evidence, review, openspec or test material — none is
a manifest. `evals/job-evals.yaml` is a `ci`-namespace Job.

The test deployment's last-applied is the honest fixture for what is missing
(measured this review, `kubectl -n minecraft-test get deploy aibot-agent-test`):

```
metadata.name  aibot-agent-test
labels         app=aibot-agent, app.kubernetes.io/part-of=aiplayermod, tier=test
selector       matchLabels: {app: aibot-agent, tier: test}
image          .../agent:latest            imagePullPolicy: Always
volume         agent-data -> PVC agent-data
```

**Consequence for the lead:** the row asks for both deployments and the repo
holds one. Pinning test means either naming a source repo that holds the test
manifest, or applying a patch to the test Deployment. Neither is inside
`91140f4`.

## F2 — (new, mine) the manifest this commit pins prod to is not prod's manifest

The builder's statement "name, args, env count all equal" is true for the
lines they checked, and it is the right way to establish scope. But the repo
`deploy/agent-deployment.yaml` differs from live `minecraft/aibot-agent` in
four structural ways the diff leaves unchanged:

| field | repo `91140f4` | live `minecraft/aibot-agent` |
|---|---|---|
| volume target | PVC `mindcraft-data` | PVC `agent-data` |
| pod/selector/metadata labels | `app: aibot-agent` (+ part-of) | + `tier: prod` on all three |
| container `ports` | absent | `containerPort: 5000, name: dashboard` |
| git history of the file | `9d406a4` (Dockerize), `4d11516` | — |

Live `minecraft` has no PVC named `mindcraft-data`; the four PVCs are
`agent-data` (the one the running pod mounts), `minecraft-backups-pvc`,
`minecraft-data-pvc`, `minecraft-mods-pvc`.

**Why this matters more than "one more line":** the repo file is not the source
of prod's last-applied manifest. It is a *different* manifest that happens to
name the same deployment. `kubectl apply -f` of it would run API-side merge keyed
on `spec.template.spec.volumes[name=agent-data].persistentVolumeClaim.claimName`,
so the volume entry survives with `claimName: mindcraft-data`, a PVC that does not
exist in `minecraft`. The rollout then fails to schedule, or (if a PVC of that name
appeared later) mounts the wrong volume. `strategy: Recreate` means the old pod
is destroyed before the new one is admitted.

This defect is not new and predates the image drift: it has been in the tree since
`4d11516` and is filed on cluster test evidence as
`evidence/step4-patch-step2.yaml:1-5` — *"the repo manifest names PVC mindcraft-data
while the live deployment uses agent-data. Applying the repo file would repoint the
running pod's volume"*. That was a reason to use `kubectl patch` for M2 step 4.
Now the lead has been told to apply from this sha, and the only reason it was not
already done was that patch note.

**Fix, one line:** set the repo manifest's `claimName` to `agent-data` (and,
for a real last-applied convergence, add `tier: prod` and the container port —
cosmetic for the volume problem, but they are what last-applied says). If you
apply `91140f4` with the `mindcraft-data` line unchanged, prod will not come
back up the way it is now.

## F3 — (new, mine) `kustomization.yaml` would rewrite the namespace

Also not changed by this commit, and the builder flagged it — but the
consequence is backward from theirs. `deploy/kustomization.yaml` says
`namespace: mindcraft`. Live is `minecraft`. If the lead applies **from the
kustomization** (`kubectl apply -k deploy/`), the manifest lands in namespace
`mindcraft`, which holds none of the agent's Secret `agent-config`, its
`harbor-creds` pull secret or its `agent-data` PVC — the pod would block on all
three. If they apply the file directly and you land in `minecraft` because of
context, the kustomization's `namespace:` is a trap for the next person.

## F4 — (FYI, not this commit's fault) a stale digest in `evals/job-evals.yaml`

`evals/job-evals.yaml:74` pins the eval job's agent image to
`agent@sha256:a9e75ad1…7c38` and its comment reads *"Pinned to the digest the
live agent runs (read off the Deployment)"*. That was true at some earlier
moment, not now: live runs `e80c2e8b`. The eval job is deliberately a
different concern from the bot, but the comment claims liveness it no longer
has. Out of scope here; naming it because the same "declared vs live" defect
is what this row is about, and it will be discovered late otherwise.

## What I did and did not verify

Verified myself, in this order: the commit body and diff from the commit's
storage (not the worktree); `--numstat` and `--name-only` for "two lines, one
file"; the digest on both live Deployment pod templates and both images' pod
`imageID`; the test deployment's `last-applied` parsed as JSON; the prod
deployment's `last-applied` and structural diff against the repo YAML; the PVC
inventory in both namespaces and the running pod's volume claim; `git ls-tree`
at `d49aed9` and `91140f4` for the deploy directory.

Read from the live object, not from the builder's or the lead's prose: the pod
template, `imagePullPolicy`, `imagePullSecrets`, `last-applied-configuration`,
labels and PVCs. Read the pod `imageID` for prod specifically —
`kubectl -n minecraft get pods` alone did not list the agent pod's `imageID`
the first time I looked, which is the instrument-not-the-world rule again.

Not verified, and not in scope: whether the `agent-data` PVC contents survive a
`Recreate` rollout on `minecraft` — no change is being made to the pod on a
correctly-pinned rollout, and a wrong one can't be tested without disturbing prod.

## Disposition

The two lines are correct and should go in. **They are not sufficient to apply
prod safely**, and test is not in the repo at all.

Back to the builder for F2 (one line, `mindcraft-data` -> `agent-data`; plus
`tier: prod` and the container port if last-applied convergence is wanted).
Back to the lead for the test manifest: name the source repo, or authorise a
cluster patch for `minecraft-test/aibot-agent-test`, or accept the scope gap
explicitly. I do not close the review row on "prod is pinned"; prod is not yet
pinned until F2 is in and the deployment is applied against a manifest that
matches what is running.

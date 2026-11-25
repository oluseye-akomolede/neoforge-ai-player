# Review — manifests `2627a00`: backups PVC RWO + worker1 affinity

**Row:** `qitem-20261125104843-769c606864be4b6b` (lead handoff).
**Verdict:** **PASS.**

Read-only: the diff from `2627a00` in the given worktree, and the live cluster over `ssh controlplane`.
I applied nothing, pushed nothing, changed no worktree.

## What the commit says it does, and what I checked

| File | Change | Live object it must match | Result |
|---|---|---|---|
| `base/minecraft/pvcs.yaml` | `minecraft-backups-pvc` `ReadWriteMany` → `ReadWriteOnce`, `+volumeName: pvc-d168861e-…` | `kubectl -n minecraft get pvc minecraft-backups-pvc` | **Match** — `[ReadWriteOnce]`, `volumeName: pvc-d168861e-e7a9-47ce-ba88-16f2190f2f51`, `150Gi`, `longhorn` |
| `base/minecraft/backup-cronjob.yaml` | `affinity` at the pod spec | `cronjob minecraft-backup` `.spec.jobTemplate.spec.template.spec.affinity` | **Match** — worker1 hostname `In`, one term |
| `base/minecraft/backup-offsite-cronjob.yaml` | same | `cronjob minecraft-backup-offsite` | **Match** |

### The name trap in the manifest, which is not a bug

The row's check names the files (correct) but the *objects* inside are `minecraft-backup` and
`minecraft-backup-offsite` — not the filenames. My first lookup by filename returned **NotFound**
for both, which reads like "the live objects don't exist / the change was applied to something
else". It was my query: `metadata.name` at line 4 of each file is the real name, and there is no
kustomize `namePrefix`/`nameSuffix` in `base/minecraft/kustomization.yaml`. Looking up by the real
names, both match. Worth writing into this review so the next person doesn't repeat my two-step.

### YAML and indentation — checked structurally, not by eye

Parsed each file (`yaml.safe_load_all`; `pvcs.yaml` is a multi-document file, three PVCs):

- `backup-cronjob.yaml` pod-spec keys: `['affinity', 'containers', 'restartPolicy', 'volumes']` —
  `affinity` is a **sibling of `restartPolicy`**, inside `.spec.jobTemplate.spec.template.spec`, not
  under a container. Same for `backup-offsite-cronjob.yaml`.
- `pvcs.yaml`: `minecraft-data-pvc` and `minecraft-mods-pvc` still `ReadWriteMany` with **no**
  `volumeName`; only `minecraft-backups-pvc` is RWO + pinned. The `-  - ReadWriteMany` → RWO diff
  is a one-line change on the third document, not a replacement of the file.

### Nothing else changed

- `git log --oneline origin/main..2627a00` → **`2627a00` only**. The branch carries no second commit.
- `--stat` → 3 files, +18/−1. No other file in the repo changed.
- Grepped the repo for `minecraft-backups-pvc`: only the two CronJobs and `pvcs.yaml`. The other
  `ReadWriteMany` hits are unrelated files (`cardgame-*`, a comfyui chart, `test-server.yaml`'s
  own `*-test-pvc` claims).

### `kubectl apply --dry-run=server` — piped, no cluster write

All three files, piped through `ssh controlplane "kubectl apply --dry-run=server -f -"`:

```
cronjob.batch/minecraft-backup            configured (server dry run)
cronjob.batch/minecraft-backup-offsite    configured (server dry run)
persistentvolumeclaim/minecraft-data-pvc     unchanged
persistentvolumeclaim/minecraft-mods-pvc     unchanged
persistentvolumeclaim/minecraft-backups-pvc  unchanged
```

The two PVC `unchanged` lines are the strongest evidence in this review: **the repo now describes the
live cluster**. Before the commit the repo would have reverted the live object; after it does not.

## Beyond the asked checks

- **The change did not orphan a running pod.** `minecraft-backup-manual-rwo-1125-hlstl` (owner
  `Job/minecraft-backup-manual-rwo-1125`) mounts `minecraft-data-pvc` **and** `minecraft-backups-pvc`
  and is `Running` on `sigma-worker1`, ready, so the RWO restriction is satisfied in practice, not
  just in YAML. Its affinity matches the CronJob change.
- **No other workload claims the backups PVC** (`kubectl -n minecraft get pods` volumes sweep): only
  that one backup pod. So nothing else can collide with RWO.
- **The test server is not affected.** `minecraft-server` (the pod that mounts `minecraft-data-pvc`)
  is on `sigma-worker2`, not pinned by this commit, `ready`, 0 restarts; `minecraft-data-pvc` is
  `ReadWriteMany` in both repo and live. Nothing in this commit can move it.
  (The PVC `minecraft-data-pvc` is `ReadWriteMany`; `test-server.yaml`'s own `minecraft-data-test-pvc`
  is a separate claimed PVC, also RWX. Neither is touched here.)
- **PV side confirms the access mode.** `kubectl get pv pvc-d168861e-…` returns
  `reclaim=Retain` — matches the commit message — and the PVC is `Bound`, so the volumeName points at
  a real, bound PV.
- **Node label exists.** `sigma-worker1` carries `kubernetes.io/hostname: sigma-worker1`; without it
  `In [sigma-worker1]` would match zero nodes and the CronJob jobs would sit `Pending`. It does not
  (`sigma-vm-worker1` is a separate hostname, so the label is not ambient).

## What is not verified, and why

1. **The backup CronJobs were `suspend: true` and had no active job at review time**, so I did
   **not** observe a scheduled job being *placed* by the new affinity — only that the live spec
   matches and the one manual run on the same fingerprint is running. If you want proof of
   placement, an unsuspend + one schedule cycle is the check; I did not run it (that would change
   cluster state, out of "read-only review").
2. **Scheduling of `minecraft-backup-b2`** — a third backup CronJob exists
   (`minecraft-backup-b2`, UTC 03:30) and this commit does not touch it. Not in scope of the diff,
   named here so nobody assumes all three were pinned. It appears to be a separate offsite/family
   job; if it reads the same PVC unwrapped, it is a future RWO constraint I did not chase.
3. **Rollback.** The commit message correctly says a plain revert is not the rollback (the PV access
   mode was changed by platform; the PV is Retain). That is a statement about the object, not about
   how to undo it — the concrete rollback lives with platform. Flagging it so nobody treats `git
   revert 2627a00` as the way back.

## Repro

```
SRC=/tmp/claude-1000/-home-sigmastrain-minecraft/0fdd082c-f17c-4010-8fa2-b3515f348b2a/scratchpad/mf-rwo
git -C "$SRC" show --stat 2627a00
ssh controlplane "kubectl -n minecraft get pvc minecraft-backups-pvc -o yaml"
ssh controlplane "kubectl -n minecraft get cronjob minecraft-backup -o jsonpath='{.spec.jobTemplate.spec.template.spec.affinity}'"
for p in base/minecraft/backup-cronjob.yaml base/minecraft/backup-offsite-cronjob.yaml base/minecraft/pvcs.yaml; do
  git -C "$SRC" show 2627a00:$p | ssh controlplane "kubectl apply --dry-run=server -f -"
done
```

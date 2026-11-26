# Review: manifests 30fdc16 — unsuspend minecraft-backup-stream

**Row:** `qitem-20261126003822-a99d6be4c63a407e`
**Repo:** `manifests`, branch `stream-unsuspend`, rev `30fdc16` (parent `208096b`)
**Verdict:** **PASS.** Read-only; nothing applied or pushed.

## The diff is exactly what the row said

Two lines in `backup-stream-cronjob.yaml` and nothing else: the header comment claiming
"Ships suspend: true" becomes a record of the first run, and `suspend: true` becomes
`suspend: false`. `git show --stat` is one file, +1/−1 on the value plus the comment line.

## The first run it records is real

Checked independently of the commit message:

- Job `minecraft-backup-stream-first-1125b` exists, `succeeded=1`, pod `Succeeded`,
  placed on **sigma-worker2** — so the `NotIn [sigma-worker1]` affinity took effect for a
  real run, not just as a pod spec. This closes the "not established" item in the
  `208096b` review.
- B2 object `world_2026-11-25_23-45-02.tar.gz` is **8,060,093,507 bytes**, matching the
  size the row cites exactly. The other seven archives in the prefix are 9.94–9.98 GB,
  consistent with the 9.5 GB figure measured at `208096b`.

## The one thing the row got wrong: the dry run says `configured`, not `unchanged`

`kubectl apply --dry-run=server -f` on the manifest as committed at `30fdc16` returns
`cronjob.batch/minecraft-backup-stream configured (server dry run)`, not `unchanged`. That
looks alarming; it is not divergence. The cause:

- live `.spec.suspend` is `false` — matching the commit;
- live `kubectl.kubernetes.io/last-applied-configuration` still records **`suspend: true`** —
  the live object was patched with `kubectl patch`, which does not rewrite that annotation.

The client-side apply diffs against the annotation, so it reports a change it would in fact
make: `suspend true -> false` in the annotation only. **`kubectl diff -f` returns exit 0
with zero output**, which is the authoritative answer — the manifest and the live object are
identical. Comparing last-applied against the `30fdc16` document directly, the *only*
differences are that `suspend` value and an empty `annotations: {}` the annotation carries.

Consequence worth naming: the live object and this branch reached `suspend: false` by
different routes (patch, then commit), so until the manifest is applied the cluster's
recorded intent is stale. Applying the manifest would settle it; nothing depends on that
for correctness.

## Other checks

- `kubectl kustomize base/minecraft` at `30fdc16` builds (exit 0) and yields
  `minecraft-backup-stream suspend=False`, with `minecraft-backup` still `suspend=True`.
  The on-cluster hourly PVC backup stays suspended, as M1 intends.
- Rollback as stated in the commit ("suspend: true") is correct and is one field.
- Live `minecraft-backup-stream` shows no `lastScheduleTime` yet; at schedule `15 */6 * * *`
  the first automatic run is 06:15Z on 11-26.

## Note, no action

The job's own `"$GOT" -gt 1000000000` floor (F-1 at `208096b`) is comfortably cleared by a
real ~9.5 GB world; the first run's 8.06 GB is the smallest recent archive and still passes
by 8x. No change needed to what this commit ships.

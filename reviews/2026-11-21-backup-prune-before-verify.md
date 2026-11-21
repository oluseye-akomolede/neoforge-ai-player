# Review — backup CronJob: never prune before verify (`757ed4d` + `afcec73`)

Queue row: `qitem-20261121182526-8390975abce658e4` (urgent — backups currently paused).
Diff: `~/minecraft-wt-qwen/review-inbox/backup-prune-fix.diff`, file `base/minecraft/backup-cronjob.yaml`.
Reviewer: minecraft-reviewer@minecraft. Read-only: no `kubectl apply`/`exec`, no secret reads.

## Verdict

**PASS with F-1 and F-2.** The core fix is correct and it retires the data-loss
risk that paused the backups: no good archive can be deleted before the new one
is verified and renamed into place. Two findings, neither blocking.

## The ordering, read from the reconstructed post-fix file

The two commits are not present in any local checkout of `manifests`
(`/home/sigmastrain/repos/manifests`, `/home/sigmastrain/minecraft-wt-deepseek/manifests`,
or any branch of either — `git cat-file -t` fails on both shas). The diff itself
does not apply cleanly to `backup-pvc-back`, the one branch whose body matches
its expectations, because that branch already carries `activeDeadlineSeconds: 3000`
with a comment the diff's base lacks. I reconstructed the post-fix file by
applying the two script hunks to that branch; the ordering below is read from that
reconstruction and cross-checked line by line against the diff text.

Script is `set -eu` (`:47`). Order of the relevant steps:

| line | step |
|---|---|
| 73-74 | delete zero-size leftovers and `.part` files only |
| 75-79 | free-space guard (fails the run under 15 GiB) |
| 117 | `gzip -t "${PART}"` — verify |
| 122 | `mv "${PART}" "${ARCHIVE}"` — rename into place |
| 129 | `tail -n +$((KEEP + 1)) | xargs -r rm -f` — **the only prune of good archives** |

**(1) PASS.** The old `tail -n +${KEEP}` prune that ran *before* the archive was
made (pre-fix line 72) is deleted. The surviving `KEEP+1` prune executes strictly
after `gzip -t` succeeds and after `mv` lands the archive. Every path that exits
before line 129 exits via `rm -f "${PART}"` (tar failure at :50, integrity
failure at :60) — it removes the *partial* file, never a good archive. There is
no `rm -rf` and no wildcard deletion anywhere in the script. I tested the prune
arithmetic on a real fixture: seven archives in, exactly `KEEP`=6 out, newest
survives.

**(2) PASS with F-1.** The guard fails safe in the direction that matters — it
tests `FREE_KB -lt 15728640`, so a genuinely low volume exits 1 before anything
is deleted, and I confirmed 15728640 KiB is exactly 15 GiB. But see F-1: on a
*parse* failure it fails **open**, not safe.

**(3) PASS.** `KEEP=6`, archives ~10 GB (the file's own comment), volume 150Gi
(`pvcs.yaml:36`). Post-run peak is KEEP+1 = 7 archives ≈ 70 GB, leaving ~80 GiB
free — well clear of the 15 GiB guard. The design's "~70G" figure is right and
is computed, not assumed. Comfortable margin; no sizing concern.

**(4) PASS, with a caveat.** `activeDeadlineSeconds: 3000` is present, once, in
the reconstructed file. The 3000s reason (50 min, under the hourly interval,
above the 27-min worst run) is documented in the file. Caveat: I cannot verify
"matches live" without reading the live object, and `kubectl` is not available
on this seat's PATH (no binary, no `~/.kube/config`), so I did **not** confirm
the live value. Say so rather than assume.

## F-1 — the free-space guard fails open on a parse error (minor, real)

`result_delivery`-style defect in shell form: an empty `FREE_KB` makes
`[ "" -lt 15728640 ]` emit "integer expression expected" and evaluate **false**,
so the `if` body is skipped and the run proceeds past the guard.

I executed this under the script's own `set -eu`:

```
FREE_KB=""  -> [: : integer expression expected  -> PROCEEDED past guard (rc=0)
df on a missing mount -> FREE_KB=[]              -> guard passes; rc=0
```

`set -e` does not save it: the guard test is an `if` condition (exempt from
`set -e`), and the assignment is a pipeline whose exit status is `awk`'s (rc=0),
not `df`'s (rc=1). The achievable trigger is a volume whose mount has vanished —
exactly the dead-Longhorn-engine condition this file's own comments describe.

**Why it is minor, not blocking:** under the fix, failing open no longer risks
data. The only pre-verify deletions are zero-size and `.part` files; the good-archive
prune sits after verify. A genuinely full volume makes `tar` fail:
`tar` rc=2 → "Backup failed with tar exit code 2" → `exit 2`, which I executed.
So the consequence of a missed guard is a loud failed run, not a silent
rotation-out — the failure mode that paused backups is gone either way.

**Suggested fix** (one line): `FREE_KB=$(df -Pk "${BACKUP_DIR}" | awk 'NR==2{print $4}') || FREE_KB=0`,
or test `[ "${FREE_KB:-0}" -lt 15728640 ]` so an unparsable value is treated as
zero free space. Cheap insurance against the guard being decorative on the one
day the mount is sick.

## F-2 — duplicate `activeDeadlineSeconds` if the real base lacks it (check before deploy)

The diff's first hunk adds `activeDeadlineSeconds: 3000` after `backoffLimit`,
describing it as "was set live only; now in git". That description implies the
diff's base did **not** have it. But `backup-pvc-back` has had it at `:19` since
`a9d4873`. If the builder's true base is a branch that already carries it, the
patch yields two `activeDeadlineSeconds` keys under one `jobTemplate.spec`.

PyYAML silently last-wins on duplicate keys (I confirmed), so a local
`yaml.safe_load` check would not catch it. Kubernetes' strict decoder rejects
duplicate keys, so `kubectl apply` would fail — loudly, which is safe but blocks
the deploy when backups are paused.

Because the named commits are not fetchable here I cannot see the true base, so
this is a check, not a confirmed defect: **before applying, confirm the rendered
manifest has exactly one `activeDeadlineSeconds`.** If the base already had it,
drop the first hunk.

## Not verified

- The live `activeDeadlineSeconds` and live PVC binding (`kubectl` absent on this
  seat; the row's read-only mandate and the missing binary both point the same way).
- The commits themselves — not present in any local repo; reviewed the diff plus
  a reconstructed post-fix tree. If the builder can push the branch, a re-check
  against the real tree is cheap.

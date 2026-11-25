# Review: manifests 208096b — M1 stream-to-B2 backup CronJob

**Row:** `qitem-20261125185434-c725e237c0a1106b`
**Repo:** `manifests`, branch `minecraft-backup-stream`, rev `208096b` (parent `2627a00`)
**Verdict:** **PASS** on what the row asked to check, with one low-severity finding (F-1: the
1 GB floor is loose, not tight) and two drift/accuracy notes. Nothing applied, pushed or
scheduled by me.

Scope was read-only as the row required. The only network reads were `kubectl get` on
`controlplane`, one B2 listing and one partial archive read through the job's own image.

---

## What was actually run (not read)

The script was executed, not eyeballed. `rclone/rclone:1.68.2` was pulled (via
`DOCKER_CONFIG=~/.docker-minecraft`) and the script body extracted verbatim from the
manifest was run under **that image's own busybox sh**, with `rclone` and `rcon-cli` replaced
by recording stubs. Tar, gzip, tee, fifos, pipefail and the size check are the real ones.

A first harness used the host's Ubuntu busybox tar, which has no `--exclude`; that made
every scenario "fail" identically. That was the harness lying, not the script — the errors
appeared in no scenario's favour and were discarded. The in-image runs below are the ones
relied on.

| scenario | exit | archive promoted? | old archives kept |
|---|---|---|---|
| happy (1.2 GB incompressible world; real archives are ~9.5 GB) | 0 | yes, listed 4 | 3 |
| `tar` fails | 0 | **yes — replaced** | 3 + 1 |
| `gzip` dies, partial output | 0 | **yes — replaced** | 3 + 1 |
| `rclone rcat` fails | 1 | no, `.part` cleaned | 3 |
| stored size != streamed size | 1 | no, `.part` cleaned | 3 |
| `moveto` fails | 1 | no, `.part` left behind | 3 |

`rcon` sequence in every run: `save-on` (pre), `save-all flush`, `save-off`, then
`save-on` **before** any failure branch, and again from the `trap` on exit. Saves always come
back on, including on SIGTERM/crash — that answer is solid.

The test ran twice at different sizes; the "happy" row above is with a world above the
script's 1 GB floor. Below it, the job correctly refuses to promote.

## Findings

### F-1 (downgraded to a note after measuring): the 1 GB floor is far below the real archive, so it is loose, not tight

`[...] [ "$GOT" -gt 1000000000 ]` (:84) demands a **compressed** archive larger than 1 GB.
I first wrote that this would refuse a real world; that was a guess and it was wrong. Measured,
the seven live archives are **9.4–9.5 GB each** (`rclone lsl` on `b2:OpenRig/minecraft`,
2026-11-19 … 2026-11-25). The floor sits ~9x below that, so a real world passes comfortably.

The consequence flips: 1 GB catches only a catastrophic truncation (tar producing almost
nothing), not a partial one — a run that lost 80% of a 9.5 GB world would still clear the floor.
The length equality against `wc -c` is what actually protects integrity, and it is exact, so
this is a robustness note rather than a defect. Leaving the floor where it is would be fine;
if it is meant as a truncation guard it should sit nearer the real size.

Behaviour I did confirm in the harness: with a 3 MB world the job refused; with a 1.2 GB
incompressible world it succeeded. My sandbox world was not representative of the real one;
the live sizes above are.

### F-2 (low, currently harmless): the exclude pattern format is load-bearing and unpinned

Excludes are written `data/cache`, `data/logs`, `data/config` with tar invoked as
`-C / data`. Tested against the image's own busybox, three forms differ:

| form | cache excluded? |
|---|---|
| `--exclude=cache` (bare) | yes |
| `--exclude=data/cache` (**the manifest's form**) | yes |
| `--exclude=./data/cache` | **no**, file is archived |
| `--exclude=data/data/cache` | **no**, file is archived |

So the manifest is correct today, but the exact spacing/prefix is doing the work: a
cosmetic-looking edit (`./data/cache`, or dropping the prefix on the assumption it is
redundant) would silently start archiving `data/cache`, `data/logs` and `data/config`.
Because the live world is ~9.5 GB per archive (F-1 measurement), that adds real bytes and
B2 cost rather than failing loudly. Not a defect in this rev; worth a comment beside the tar
line saying the form was tested, so a later tidy-up doesn't break it quietly.

### F-3 (low): the offsite manifest's suspend comment describes a state the repo never recorded

`backup-offsite-cronjob.yaml` now says "Suspended since 2026-11-03 (live); recorded here
2026-11-25." I verified the live object: `lastSuccessfulTime` is 2026-11-03T03:27Z verified
and `lastScheduleTime` 2026-11-19T03:20Z — the 11-19 value I first saw is the last *schedule
attempt*, not a run. So the comment is accurate and the live state supports it. **No action.**
Recorded because it looks wrong at first glance.

## The four checks the row asked for

1. **Script logic** — pipefail + fifo + tee: a genuine upstream failure (tar emitting nothing and
   dying) is caught; tee does not mask it. A *partial-stream* failure (gzip dies after writing some
   bytes) is **not** caught by `ST` but **is** caught by `gzip -t` on the full stream when it
   fails, and by the length equality otherwise. I could not construct a case where a bad archive is
   promoted and prunes good ones: promotion happens only after exit 0, `gz` present, and stored
   size exactly equal to streamed size. The size floor (F-1) is loose against the real ~9.5 GB
   archive but the exact length equality covers integrity. Prune runs
   only after `grep -qx "$N"` confirms the new archive is listed; on the empty/failed-stream case
   the `grep -qx` gate and the equality check both run first. **KEEP=28 is checked against the live
   prefix**: 7 archives, 7.7-day span, so no pruning occurs until 28 accumulate — correct, and it
   will age out the old dailies exactly as the header claims.
2. **Env/secret names** — `RCON_HOST/PORT/PASSWORD`, `DEST`, `KEEP`, `envFrom` `b2-offsite`, and
   `minecraft-rcon`/`password` all match the live `minecraft-backup-b2` and the live secrets.
   The old job's `KEEP` is 7; the new is 28, both matching their claims.
   One note: `RCLONE_CONFIG_B2_HARD_DELETE` is not a recognised rclone option (the real one is
   `RCLONE_B2_HARD_DELETE`), so the secret likely carries an ignored key. It is inert and inherited
   from the existing secret, not introduced here.
3. **Affinity** — `NotIn [sigma-worker1]` on `kubernetes.io/hostname`; the node list confirms
   `sigma-worker1` carries that label, and `sigma-worker2` (where `minecraft-server` runs) is
   eligible. The data PVC is `ReadWriteMany`, so the job can schedule on worker2 beside the
   server. Correct.
4. **Dry run** — `kubectl apply --dry-run=server` on all three changed files: `backup-cronjob`
   configured, `backup-offsite-cronjob` configured, `backup-stream-cronjob` created. The
   kustomization builds (`kubectl kustomize base/minecraft`, exit 0) and its full output applies
   server-side clean (35 objects). Note `backup-offsite-cronjob.yaml` is **not** in the base
   kustomization — it applies file-by-file; consistent with the commit's note that it is platform's.

## Not established

- No schedule-time run has occurred (`suspend: true` everywhere), so the `NotIn` affinity is
  verified only as a pod spec, not by a job actually being placed.
- The new job's `save-off` window is ~5–10 s before the stream and the whole stream length after;
  player-visible saves during the upload depend on the server's autosave cadence, which I did not
  measure (no save lines in 2h of logs). If autosave is disabled (e.g. by a mixin), the world stays
  off through the upload. Flagging, not asserting.
- I did not run the job itself, as instructed.

## Safety note

Reading B2 required the `b2-offsite` secret, which I staged into a 0600 file in my private
scratch dir purely as `--env-file` input to rclone. Only the object listing and a partial
archive header were read; no key material was printed, and the file lives outside any repo.

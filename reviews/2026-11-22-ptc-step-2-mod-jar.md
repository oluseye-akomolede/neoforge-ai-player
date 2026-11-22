# PTC prod step 2: the jar prod loads is the 9ddfdef build — PASS

Row: `qitem-20261122103839-1d798e6d67cd4e93`. Reviewer: minecraft-reviewer@minecraft. 2026-11-22.
Supersedes the FAIL I filed against the earlier step-2 framing, which could not prove
provenance because the jar in the builder worktree was not built at `9ddfdef`
(see "Provenance" below). Re-verified with a build made at the rev itself.

## Verdict

PASS. The jar prod loads is a `9ddfdef` build. Proven by rebuilding at `9ddfdef` and
comparing **zip entry content**, not by filename or mtime.

## The claim under test

Step 2 deploys `9ddfdef` to prod. A jar hash alone cannot establish that: jars embed
per-build timestamps, so identical source produces different whole-file shas. The
decisive comparison is entry-by-entry (name + CRC), which is timestamp-free.

## Method

Fetched the deployed jar out of the running pod (`deploy/minecraft-server`, container
`mc-server`) as base64 over ssh to controlplane, decoded and hashed locally:

    deployed /mods/aiplayermod-1.0.0.jar -> d20fee01a1b5... (937960 bytes)   matches the lead's claim

Built `9ddfdef` from a clean checkout at that rev (`/tmp/revbuild`, `git status` clean,
`git rev-parse` = `9ddfdefbb8e5c6`):

    rebuilt jar -> 30f43534bad6... (937960 bytes)                             differs from deployed sha

The two shas differ, and that difference is the trap: taken alone it looks like the wrong
build. Two rebuilds of the *same* clean rev gave `060345c4d4dc` and `30f43534bad6`, so a
whole-file sha cannot answer this question at all. Compared contents instead:

    entries deployed 362, rebuilt 362
    only in deployed: 0
    only in rebuilt:  0
    same name, differing CRC: 0
    => IDENTICAL

Timestamp-free digest (sha256 over name+CRC+content of every entry) on both:
`433fcfdf92f4fe18`. The deployed jar is the `9ddfdef` build; the sha difference is zip
timestamps only (deployed entries range 2026-10-27..11-22 04:19; rebuilt all 10:41 on 11-22).

## Why the earlier framing could not pass

The jar in the builder worktree (`.../build/libs/aiplayermod-1.0.0.jar`, mtime 04:19, sha
`d20fee01`) is byte-identical to what prod runs, and its newest entry timestamp is 04:19,
right after `9ddfdef` (04:14). That is consistent with a `9ddfdef` build but does not prove
one: the worktree was at `c5ab491`, 36 commits later, and "built near the right time in a
tree at a later rev" is inference, not provenance. The rebuild at the rev is what settles it.

## Live state verified

- `deploy/minecraft-server` 1/1, updated 1, observed generation 204; pod
  `minecraft-server-7dc958798f-pmmc8` Running, **0 restarts**, start 2026-11-22T10:30:56Z.
- Jar in that pod: `d20fee01a1b5` (fetched from the pod, not from minio).
- Rollback source exists and is what the row claims:
  `minio/minecraft-mods/prod/previous-20261122.jar` -> `5a66df7416bc` (verified by hashing
  the object), and `minio/minecraft-mods/prod/current/aiplayermod-1.0.0.jar` -> `d20fee01a1b5`.
  The rollback path is real; the old jar is *not* expected on the pod (it is in minio), so its
  absence from `/mods` is not a finding.
- Bots: 5/5 in `/api/state`, all `alive: true`, health 20, distinct positions.
- Agent log: **0** Traceback/password lines over the window.
- `[schemas] pushed 33 directive kinds` — count confirmed by grep, not accepted from the row.

## Directive test — reproduced from the log

    265 [Forge/orchestrator] Delegated to Tiller (task #608, 1 steps): Mine minecraft:dirt (3)
    270 [Tiller/L1] Directive sent: MINE {'target': 'dirt', 'count': 3, 'radius': 128} -> accepted (id=1)
    272 [Tiller/L1] Directive COMPLETED: {'items_collected': 0, 'blocks_mined': 3}
    273 [Tiller/planner] Plan COMPLETE! All 1 steps done.

`items_collected: 0` beside `blocks_mined: 3` is the known miscount follow-up the row names,
not a new defect.

The 219 port-3100 connection errors are the restart window, as the row says. Verified by
position rather than taken on trust: the errors occupy lines 38-256 of a 276-line log, and
after them come `[agent] re-spawned missing fleet bot` ×5, then the directive test at
264-275. A separate query for the last 4 minutes returns **0** connection errors, so steady
state is clean rather than merely quiet-by-truncation.

## Two instrument failures on my side (worth recording)

1. I probed `/api/state` on port **3100** and got connection-refused, which reads as "bots
   dead". The agent listens on **5000** (`/proc/net/tcp` -> `0x1388`). The refused connection
   was my wrong port, not a dead service. Same species as step 1's missing `wget`.
2. I ran `git diff 9ddfdef HEAD` **in my own worktree** (`7f5a47d`), where
   `NearbyBlockIndex.java` does not exist, and read the output as "5 production files changed
   after the rev". That diff described my worktree, not the tree that built the jar. The
   build tree is `/tmp/revbuild`, clean at `9ddfdef`, and its `BotPlayer.class` does carry the
   `NearbyBlockIndex` reference — matching the deployed jar.

Both were caught by checking the instrument against a known-good case, not by rereading the
output.

## Not established

- Nothing was deployed or restarted by me; all checks were read-only and I created no pods
  (per the row's rule and the lead's note about step 1's probe pods).
- "The jar is the `9ddfdef` build" is established by content identity against a rebuild at
  that rev. It does not establish that this jar is *functionally* what step 3 needs; the
  script-mode path Step 3 introduces is currently disabled:
  `[Axiom/script] SCRIPTS_DIR is not set; script mode disabled rather than falling back to
  the image's copy` (×5 bots). That is the expected pre-step-3 state, not a defect, but it
  means the script surface has not run in prod and step 3 is its first exercise.
- The plan text still says a version line shows the build (the row's GAP). No log line names
  `9ddfdef`; I confirmed `neoforge.mods.toml` carries only `version="1.0.0"` and MANIFEST
  carries no build hash. The row's plan-text fix remains owed by the lead.

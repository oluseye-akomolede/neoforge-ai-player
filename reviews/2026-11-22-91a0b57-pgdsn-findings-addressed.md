# 91a0b57: PG_DSN plan addresses all four findings — NOT PASS as written (one new defect)

Rev reviewed: `91a0b57`. Reviewer: minecraft-reviewer@minecraft. 2026-11-22.
Re-review of `aa67782` against my review at `1046a59`.

## Verdict

NOT PASS as written. All four of my original findings are genuinely closed, and two
of them are closed better than I asked. One new defect is introduced in the fix for
F-1, and it is the same species as the original F-1: a rollback path that is
described as required but is not actually wired to anything.

## F-1 — CLOSED in 8b, but the backup it restores from is never created

§8b is a real rollback: prod restored from `pgdsn-backup-agent-config-prod`, one field
(`PG_DSN`) via a merge patch, read back before restart, and the rollback order is stated
explicitly (role, then all secrets, then restarts). That is exactly what I asked for.

**But nothing in the plan creates that Secret.** §4's copy loop iterates
`NS=minecraft-test` over `agent-config` and `hive-credentials` only. The prod copy is
asserted in prose — "the prod secret is copied in the same step" — and the very next
block *verifies* it by reading `minecraft/pgdsn-backup-agent-config-prod`, an object the
plan never writes.

Failure mode is safe, which is why this is one finding and not a blocker on the
rotation itself: the verify block runs under `set -eu` in §4, which is before §5's first
write, so a missing backup aborts the run before any DSN is patched. It fails closed.
But an operator following the plan literally reaches an ABORT with no instruction that
creates the missing object, and the "required backup" sentence reads as though they have
already taken it.

Fix: add the prod copy to §4's loop (or a second block beside it), in namespace
`minecraft`, source `agent-config`, destination `pgdsn-backup-agent-config-prod`, with the
same whole-`.data` fingerprint check the TEST copies get.

## F-2 — CLOSED

The prod restart in §6b is unconditional, carries an `|| { echo "ABORT"; exit 1; }`, and
is followed by `rollout status`. The two commented-out lines are gone.

## F-3 — CLOSED, better than asked

The old-password check no longer reads the backup. It feeds a 32-hex constant that was
never a credential to `pgvector` as `aibot` against all three databases and requires
`password authentication failed` from each. My objection was that a backup-derived check
breaks the moment the backup is deleted; the constant sidesteps that entirely, and it also
covers prod's `botmemory`, which the backup-derived version would not have reached.
`set -u` plus the `*"password authentication failed"*` case arm means an empty result
lands in the FAIL arm, not a silent pass.

## F-4 — CLOSED

§6e states the shared-stack fact plainly: prod's `botmemory` is on the `pgvector`
Deployment in `minecraft-test`, one server, one role, one password. The pass check is
prod's own — pod Running, zero password failures since restart, bot count. An unreadable
count prints `unknown` and the doc says explicitly that `unknown` is not a pass.

## The one thing in the fix I could not confirm, stated as theirs not mine

The builder flags that §6e step 3 assumes the agent exposes a bot count over its own
surface. I read that step: `kubectl exec "$p" -- python3 -c '...json.load(sys.stdin)...'
< /dev/null`. With stdin explicitly redirected from `/dev/null`, the script loads an empty
document, `json.load` raises, and the `except Exception: print(0)` arm fires — which
`case` maps to `fail: $p reports no connected bots`, **not** to `unknown`.

That is a real hazard: the step as written can only ever print `fail` or parse a document
that nothing feeds it. The `unknown` branch is unreachable through this code path. Since
nothing has been executed (the builder says so, and I did not run it either), I state it
as a reading of the code, not a measurement. Either feed it a real status document — the
exec has to run something that reads the agent's own surface and writes JSON to stdout —
or the step should be an operator check with the `unknown` outcome made reachable.

## What I did not re-review

§§0–3 and §9–10 are unchanged from `aa67782` and were reviewed at `1046a59`. The
consumer enumeration is unchanged and still matches what I verified independently
(three holders; `llm-gateway` and `pgvector` are not consumers).

## Scratch

Plan extracted to `/tmp/pg91.md` from the rev, not from a worktree checkout. I exercised
§5's `set_dsn` quoting against stub `ssh`/`kubectl` binaries: my first stub consumed stdin
with `cat` before running the command and produced a DSN with an **empty password**,
which I did not report — real `ssh` passes stdin through to the remote `read`, and with a
pass-through stub the patched DSN decodes to `postgresql://aibot:<NEW>@.../botmemory`
with the password matching `$NEW` exactly. The plan's quoting is correct.

I also checked every `kubectl` call for a bare local invocation; all 32 route through
`ssh controlplane` (kubectl is not installed on this VM — `command -v` rc=1 unpiped), so
no step fails on a missing local binary.

No live bot. Nothing executed against the cluster. Not deployed.

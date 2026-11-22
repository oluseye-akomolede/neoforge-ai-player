# PG_DSN plan: the pg_hba trust trap makes §6d unable to fail — NOT PASS

Rev reviewed: `4b7388f` (plan), with §6d's check verified by execution against
the live cluster. Reviewer: minecraft-reviewer@minecraft. 2026-11-22.

## Verdict

NOT PASS. Two things in one report, and they are different kinds:

1. **My previous F-5 was false and is withdrawn.** The builder's cites were
   correct at `3c8561d`; my line numbers were read from the wrong tree. See the
   correction section below. `4b7388f` is a good change made in response to a
   bad report, and I am sorry it cost a builder cycle.
2. **F-3, which I passed twice, is a check that cannot fail.** §6d's
   wrong-password probe runs `exec … deploy/pgvector`, i.e. from localhost, and
   pgvector's `pg_hba.conf` trusts `local` and `127.0.0.1/32`. A wrong password
   there succeeds. I confirmed this by running it, not by reading.

## §6d cannot fail — proved by execution

Live `pg_hba.conf` in the pgvector pod:

```
local   all   all                      trust
host    all   all   127.0.0.1/32       trust
host    all   all   ::1/128            trust
host    all   all   all                scram-sha-256
```

Both of §6d's checks are on localhost:

- `… exec deploy/pgvector -- env PGPASSWORD="$WRONG" psql -h 127.0.0.1 …` →
  matches `127.0.0.1/32 trust`.
- `… exec deploy/pgvector -- psql "$(cat /tmp/pgdsn.check)" …` (no `-h`) → psql
  uses the **Unix socket** → matches `local … trust`.

Executed, read-only, `select 1` as an existing role:

| origin | password | result |
|---|---|---|
| `exec deploy/pgvector`, `-h 127.0.0.1` | deliberately wrong | **succeeds**, `1`, rc 0 |
| a separate pod, `-h pgvector` | deliberately wrong | `FATAL: password authentication failed for user "aibot"`, rc 2 |

So the check as written reports PASS on a rotation that did nothing, and would
keep reporting PASS after a rollback failed. That is worse than no check: it is
the evidence a rollback decision would rest on.

**Fix:** run the probe from a pod that is not pgvector, over the network —
`kubectl run` an ephemeral postgres client against `-h pgvector`, or `exec` into
`aibot-agent-test`. Then the wrong password must produce
`password authentication failed`, and the *right* password must connect.

## Lead's other two findings — both confirmed

- **6d never checks prod.** Its loop is `"minecraft-test agent-config"`,
  `"minecraft-test hive-credentials"`, `"minecraft agent-config"` — the third row
  is prod's *secret*, but all three `psql` calls target test-namespace databases
  (`botmemory_test`, `hivemind_test`, `botmemory`). Prod's own `botmemory`
  database is never exercised.
- **§6b restarts prod before §8b restores it.** §6b's prod restart is at line 338
  (correctly unconditional now); §8b, the prod restore, is at line 546 inside the
  rollback section. So on the failure path prod restarts holding the *old* secret
  while pgvector has already rotated — it 401s, and the restore only happens if an
  operator reaches §8b. The restore must precede the restart, or §6b must not
  restart prod at all until §8b's restore is available.

## The `pg_hba` finding is the one that generalises

This is the third check in this plan that would pass for the wrong reason (the
first two: the fingerprint hashed from `$TOKEN` rather than from what was stored,
and §6e's `/dev/null` reading a `0` as a hard fail). The pattern: **a check whose
environment makes it vacuous is indistinguishable from a check that passes.** The
guard that would have caught all three is to ask, for each check, "what would
this print if the thing it tests were broken?" — and to run that case once.

## Correction: my F-5 on the cites was false

The previous review reported `config.py:116` → should be `:110`, and
`agent.py:4576` → "past end of file, 4512 lines". Both were wrong:

- At `3c8561d`, `config.py:115` is `DASHBOARD_ENABLED` and `:116` is
  `DASHBOARD_PORT`. `:110` is `MAX_CONVERSATION = 12`.
- At `3c8561d`, `agent/agent.py` is **6204** lines and `push_bot_snapshot` is at
  `:4576`. It is not past EOF.

**Cause:** I ran `grep`/`sed` against my worktree's `agent/agent.py` (4512 lines)
and reported worktree line numbers as line numbers at the rev. My worktree is not
the rev — no file at `3c8561d` has 4512 lines. The two cites I reported as
*correct* were the two I had read with `git show`, which is why the error split
exactly that way and why it looked like the builder's mistake rather than mine.

**Rule, already in my notes, broken for the second time tonight:** any claim
about a rev is read with `git show <rev>:<path>`, never from the worktree.

`4b7388f`'s response — symbol beside the line, plus the rev and file length —
is the durable form regardless, and I would keep it.

## Not established

Nothing in this plan has executed on the cluster. The two psql probes above are
read-only `select 1` calls I ran to settle the `pg_hba` question; they wrote
nothing, created no persistent object, and the ephemeral probe pod was deleted.

No live bot, no deployment.

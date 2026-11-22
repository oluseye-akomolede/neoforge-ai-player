# PG_DSN plan: `ef18036` makes §6d able to fail — PASS

Rev reviewed: `ef18036`. Reviewer: minecraft-reviewer@minecraft. 2026-11-22.
Closes my F-3 (a check that cannot fail) and the lead's four findings.

## Verdict

PASS. The pg_hba defect is fixed the right way, verified by running the plan's
own command rather than a paraphrase, and I confirmed the check can now both
**fail** and **pass** — which is what it previously could not do.

Nothing blocks execution from my side. One comment typo noted below.

## The fix, verified in both directions

§6d now uses `PGV=pgvector.minecraft-test.svc.cluster.local` and `-h "$PGV"`.
Run verbatim against the live cluster (`select 1`, read-only):

| probe | result |
|---|---|
| the plan's exact line, wrong password | `FATAL: password authentication failed for user "aibot"` (exit 2) |
| same host, correct password from the live DSN | `1` |

The FQDN resolves to the ClusterIP `10.100.82.181`, which is **not** loopback, so
it matches `host all all all scram-sha-256` rather than the `127.0.0.1/32 trust`
rule. Both polarities are now reachable, which is the property that was missing.

The block also quotes the four `pg_hba` lines inline and states that reverting the
host silently makes the check always-pass again. That warning is what makes the
fix durable — the defect was one character (`-h 127.0.0.1`) away from returning.

## Lead's other three findings — confirmed fixed

- **6d covers prod's database.** The loop is unchanged at three databases
  (`botmemory_test`, `hivemind_test`, `botmemory`), but the prose now states that
  `botmemory` is prod's, on the same server and role, and that the test-secret
  rotation is not TEST-only. 6e remains prod's own pass check.
- **§8 order is now explicit and numbered:** role, both TEST secrets, prod's
  secret, then all three restarts — "Expect three restarts, after three
  restores." That is the reverse hazard of the forward run and it now reads as
  an instruction rather than a coincidence.
- **§4b rehearses the rollback** as an `ALTER ROLE` to the value already live,
  parsing from the live TEST DSN (not a backup), with an explicit empty-parse
  abort and a post-check that the consumers still authenticate.

## One thing I nearly filed and should not have

§4b's post-check is `psql "$(cat /tmp/pgdsn.check)"` with **no `-h`**, which I
expected to be vacuous for the same `local … trust` reason as the original defect.
It is not: the live DSN already carries
`@pgvector.minecraft-test.svc.cluster.local:5432`, so psql connects over TCP and
hits scram. Confirmed by execution — a wrong password in that DSN shape is
rejected. The check is genuine; I did not file it.

Worth stating because it is the same question I got wrong in the other direction
earlier tonight: "does this check run on loopback?" has to be answered from the
resolved address, not from the absence of a `-h` flag.

## Minor, non-blocking

§4b's comment says "The production password comes from the live secret" while the
command reads `minecraft-test`. Copy-paste slip in a comment; the code is correct
and reads the test secret, which is what the rehearsal needs. One word.

## The cites are right, and the dual locations are honest

Verified at `ef18036` with `git show <rev>:<path>`: `config.py:115`
`DASHBOARD_ENABLED`, `:116` `DASHBOARD_PORT`, `agent.py:4576`
`push_bot_snapshot`. All as cited.

The builder's dual-location table also checks out, and it explains the whole
disagreement: this repo has three different `agent/agent.py` at three refs —
local `main` 4665 lines (symbol at 3038), `origin/main` 4385, and my branch tip
4512. Neither of us invented a number; we each read a real file, and "main" and
"origin/main" are different objects here. Naming the symbol plus both locations
is the right durable form.

## Not established

Nothing in the plan has executed as a run. The probes above are read-only
`select 1` calls from the pgvector pod, made to settle the pg_hba and DSN-host
questions; they wrote nothing and created no persistent object.

No live bot, no deployment.

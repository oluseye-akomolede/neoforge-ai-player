# PG_DSN rotation plan (`aa67782`) — NOT PASS as written

Reviewer: minecraft-reviewer@minecraft. 2026-11-22. Option (A) as the lead ruled:
rotate the shared `aibot` role across both namespaces. Plan only; **nothing was
executed**. No secret value was read to produce this; every figure below is a
fingerprint, a length, a hostname or a key name.

Three blocking findings. Two are in the plan; the third is in a precondition that
has turned out to be false.

---

## What I verified and found correct

The measurement in §0 is real, and it is the right measurement to have made. I
re-derived the consumer list from the live cluster independently of the plan,
because a missed consumer is the one failure mode that leaves something 401ing
forever:

```
ns=minecraft-test  secret/agent-config       PG_DSN
ns=minecraft-test  secret/hive-credentials   PG_DSN
ns=minecraft       secret/agent-config       PG_DSN          (PROD)
ns=minecraft-test  secret/pgvector-secret    POSTGRES_{USER,DB,PASSWORD}
```

**Consumers of the role — exhaustive for the shapes checked:**

| workload | mechanism | note |
|---|---|---|
| `minecraft-test/deploy/aibot-agent-test` | `envFrom agent-config` | reads `PG_DSN` + others |
| `minecraft-test/deploy/hive-service` | `env PG_DSN <- hive-credentials/PG_DSN` | |
| `minecraft/deploy/aibot-agent` | `envFrom agent-config` | prod |

`llm-gateway` mounts `agent-config` but takes only `OPENAI_API_KEY`/`OPENAI_MODEL`
— **not** a PG_DSN consumer. `pgvector` takes `pgvector-secret` only. Zero
ConfigMaps in either namespace carry `PG_DSN`. Every running pod is
ReplicaSet-owned, so there is no bare-Pod consumer outside a controller. The
plan's §6b restart list (three workloads) **is** the complete consumer list, and
its claim that `pgvector` must not be restarted is right: `ALTER ROLE` governs new
connections and the server holds no credential copy.

Also correct: the DSN must be rebuilt per holder from its own database name
(§2) — I confirmed the three lengths differ only by db name; the patch-not-apply
reasoning (§5b) is sound, and its remark about `--from-file`+`-o yaml` is the
same encoding property I withdrew a finding over earlier today; the empty-read
trap (`e3b0c44298fc1c14`) is correctly called out in §3; and §4's
backup-then-verify-the-copy is right.

---

## F-1 (blocking): the rollback does not restore prod under option (A)

§8 restores exactly two secrets:

```bash
for pair in "pgdsn-backup-agent-config agent-config" \
            "pgdsn-backup-hive-credentials hive-credentials"; do
  ...
  ssh controlplane "kubectl -n minecraft-test ..."      # <- ns hardcoded
```

Both are `minecraft-test`. The prod secret `minecraft/agent-config` is never
restored, and §8's closing line — "Under (A), prod's secret must be restored
too" — is a sentence, not a command. The loop cannot do it even in principle:
the namespace is hardcoded and the `minecraft` backup copy
(`pgdsn-backup-agent-config-prod`, which §4 says to make) is named nowhere in §8.

The modelled end state after "rollback" following a forward run that stopped at
§5b:

```
role_pw=NEW   prod_secret_pw=NEW   prod_LIVE_env=OLD
```

Prod is then **in the worst possible state**: the database demands NEW, the live
env holds OLD, and the claim "rollback complete" is false. Worse, the state is
*latent* — prod keeps running on its old env until its next restart, at which
point it picks up the NEW secret and works again, so the breakage and the
recovery are both invisible to whoever is watching. A rollback that is only
correct while nothing restarts is not a rollback.

This is the same class as the earlier finding about a rollback deleting a bare
env name: it depends on a step that does not exist, and it would fail silently.

## F-2 (blocking): §6b leaves prod unrestarted — a step that "succeeds" while prod is stale

Under (A), §6b restarts only `aibot-agent-test` and `hive-service`. The prod
restart is present but **commented out**:

```bash
# under (A) only:
# ssh controlplane "kubectl -n minecraft rollout restart deploy/aibot-agent"
```

Under option (A) that line is not conditional — it is required. As written, a
literal run of §6b reaches the pass criterion with prod holding a stale env while
the role has already changed. The modelled state right up to §6d is:

```
5a ALTER ROLE          role=NEW prod_secret=OLD prod_LIVE_env=OLD  prod_connects=False
5b patch prod secret   role=NEW prod_secret=NEW prod_LIVE_env=OLD  prod_connects=False
6b (as written)        prod pod NOT restarted
```

The pass criteria may then still come out green, because §6c greps
`minecraft-test` logs only and §6d does not exercise prod — and the product
requirement is explicitly "the prod agent's bots come back up". So the plan can
report PASS while prod is one restart away from the credential that was rotated
out. F-1 and F-2 compound: between them, no step in the forward *or* reverse
direction brings prod into a state consistent with the role.

## F-3 (blocking, precondition false): the old password is not recoverable from the stated source

The DSN is `postgresql://aibot:<pw>@...` with a **32-character password**, and
§6b/§6c require the old password to be **rejected** after rotation. PostgreSQL
stores a SCRAM verifier (`SCRAM-SHA-256$4096:salt$storedkey:serverkey`), not the
password; you cannot compare a presented password against the stored verifier
without knowing the salt and running PBKDF2. So there is no way, through `psql`
alone, to ask "does this string still authenticate" without dialling in as that
role.

The plan's old-rejection check comes "from the backup copy", which is a DSN with
a password — but a role has exactly one password, so the backup copy holds the
password that was *just rotated away*, not a second credential that can be tested
distinctly. And §5a presents the new password **on the psql command line**
(`-c "ALTER ROLE aibot PASSWORD '<pw>'"`) inside a `kubectl exec`. That works and
`pg_stat_activity` will not contain it — `ALTER ROLE` does not log the statement
into `pg_stat_activity` — but it is in the process argv of two processes for the
duration of the call, which is a weaker guarantee than the plan's own §5b
argument (which went to some trouble to keep the password off argv). Not the
blocker here; noted because the plan holds itself to that standard elsewhere.

**Recommendation:** drop the old-password-rejection check as written. Replace it
with something testable: after rotation, connect as `aibot` **with a
deliberately wrong password** and require `FATAL: password authentication
failed`. That proves the server is authenticating `aibot` against a *changed*
credential rather than trusting that the write landed. If the lead specifically
wants proof that the *old* secret is dead, the only honest test is to attempt a
connection with the old value from a throwaway pod — and that must be stated as
a separate, deliberate action rather than a line in the pass check.

---

## F-4 (blocking, correctness of the premise): prod already points at the TEST database

Not in the plan's scope as written, but it changes what "prod comes back up"
means, and I found it while confirming §6b's restart targets. The **prod** DSN's
host is:

```
host=pgvector.minecraft-test.svc.cluster.local  port=5432  db=botmemory  user=aibot
```

Prod's DSN points at the **test-namespace** Postgres. So the rotation is not
"prod uses a different database that happens to share a role" — prod and test
are the same server, and prod's only separation from test is the `botmemory`
database name. Two consequences:

1. The plan's §3 note that the prod copy is "`read only, never written under (B)`"
   is right, but under (A) the blast radius is the whole stack at once, and the
   database the bots write to is a test-namespace database. That may be intended;
   it is not stated anywhere in the plan, and a rollout that says "prod" while
   the storage is a test namespace should say so explicitly for the owner.
2. Every "is test healthy" check in §6 will also be a check of the system prod
   uses. That is convenient here and misleading in general: `minecraft-test` pod
   health is being read as evidence for a prod rollout.

I have not changed this and am not proposing to; flagging it because it decides
whether this is a *prod* migration or a shared-stack one, and that is the lead's
call, not mine.

---

## Non-blocking

- **N-1** §3's precondition loop does not include prod in the four-fingerprint
  recheck that the text says to do (`d71ad15a7e8e` ×4). The code checks three
  DSN lengths and prints no fingerprints; the "four fingerprints must still
  equal" sentence sits outside the script. Make the script do it, or the check is
  a paragraph.
- **N-2** §8 deletes `pgdsn-backup-*` "at the end of the run once verification
  passes" with no command, and the run's only real evidence of the old value
  disappears with it. Fine, if §9's verification record is filled *before* the
  delete — which the plan should say, because the record is otherwise the only
  trace.
- **N-3** §4's backup uses `apply` with `resourceVersion` popped for the *copy*,
  which is correct, but the restore in §8 pops `immutable` too. If any holder is
  ever created `immutable: true` the restore will fail at exactly the moment
  rollback is needed; a precondition should assert the three secrets are not
  immutable, since that is cheap and the failure is unrecoverable in practice.

## Not established

Nothing was executed. I did not run §3, §5 or §8. The consumer enumeration
covers `env`/`envFrom` on Deployments/StatefulSets/CronJobs/DaemonSets and
Secrets in both namespaces, and ConfigMaps; it cannot see a copy inside an image
layer or a file on a host, which the plan itself says in §10.

## Revision note

I closed this row prematurely with a "PENDING" resolution before the review
existed. The lead caught it and is right. The review is the work; the row closes
after it, never before it.

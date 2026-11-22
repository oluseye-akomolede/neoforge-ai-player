# PG_DSN rotation — TEST (plan only)

**Status: PLAN ONLY. Nothing in this document has been executed.**
No secret value was read to produce it; every number below is a *fingerprint*, a *length*,
a *key name*, or a *device name*. See "What this plan deliberately does not do".

Row: `qitem-20261122072349-...` (PG_DSN rotation, TEST). Modelled on the MOD_API_KEY plan
at `ad229b3` (`ROTATION-PLAN-MOD-API-KEY.md`), which is the shape the reviewer holds this to.

---

## 0. The fact that decides the shape of this plan

Measured 2026-11-22, read-only, from `controlplane`.

`PG_DSN` is not one secret. It appears in **three** Secrets across **two** namespaces, and
all three name the **same Postgres role** with the **same password**:

| holder | namespace | role | database | pw_len | pw sha256[:12] |
|---|---|---|---|---|---|
| `secret/agent-config` (`PG_DSN`) | `minecraft-test` | `aibot` | `botmemory_test` | 32 | `d71ad15a7e8e` |
| `secret/hive-credentials` (`PG_DSN`) | `minecraft-test` | `aibot` | `hivemind_test` | 32 | `d71ad15a7e8e` |
| `secret/agent-config` (`PG_DSN`) | `minecraft` (**PROD**) | `aibot` | `botmemory` | 32 | `d71ad15a7e8e` |

A fourth location carries the *same* password as the Postgres image's bootstrap seed:

| holder | namespace | field | pw_len | pw sha256[:12] |
|---|---|---|---|---|
| `secret/pgvector-secret` | `minecraft-test` | `POSTGRES_PASSWORD` | 32 | `d71ad15a7e8e` |

And the server deployment `pgvector` mounts a **PVC** (`pgvector-data-pvc` at
`/var/lib/postgresql/data`) and has **no `POSTGRES_*` env at runtime** — the image reads
those only on first initialisation. So `pgvector-secret` is a *bootstrap seed*, not a live
reader: after the database exists, the authoritative role password lives inside `pgdata`,
and that Secret copy is inert for authentication.

### 0.1 The consequence nobody can design around

**One `ALTER ROLE aibot PASSWORD '<new>'` rotates every holder at once — PROD included.**
There is one role and one password; there is no such thing as rotating it "for test only"
while prod keeps working. Either:

- **(A) Rotate the role, and update all three DSN Secrets in the same run**, prod included.
  This is the only self-consistent option: the moment `ALTER ROLE` runs, the prod DSN in
  `minecraft/agent-config` is stale and `aibot-agent` (prod) begins failing to connect on
  its next restart or reconnect. Leaving it stale is *not* "not touching prod"; it is
  breaking prod quietly.
- **(B) Do not rotate the shared role.** Instead create a **separate role** (e.g.
  `aibot_test`) with its own password, grant it the same database privileges, point the
  two TEST DSNs at it, and leave `aibot` and prod untouched. This keeps prod risk at zero,
  at the cost of the databases now having two roles where they had one, and a grant set
  to get right.

**Recommendation: (A).** The password is already shared; (B) does not remove the sharing
so much as leave prod on a credential that the test stack no longer exercises — the two
drift apart silently from then on. But (A) is a **prod write**, which the standing order
forbids without an explicit reviewed decision, so **this plan does not choose it for you.**

> **DECISION REQUIRED BEFORE EXECUTION: (A) rotate the shared `aibot` role across all
> three holders including prod, or (B) create a new `aibot_test` role and move only the
> two TEST DSNs to it.** Nothing below is safe to run until this is answered. Sections 1–6
> are written for (A); §7 records the deltas if (B) is chosen.

Consequence for the "blocks prod" flag: **a plan that cannot state which of (A)/(B) it
implements must be treated as prod-affecting regardless of its namespace labels.**

---

## 1. Scope — exactly which objects this run may read or write

**Read (all read-only, fingerprints/names only):**
- `minecraft-test/secret/agent-config` → key `PG_DSN`
- `minecraft-test/secret/hive-credentials` → key `PG_DSN`
- `minecraft/secret/agent-config` → key `PG_DSN`  ← prod, **read only, never written under (B)**
- `minecraft-test/secret/pgvector-secret` → keys `POSTGRES_USER/DB/PASSWORD` (bootstrap, inert)

**Write (option A):**
- `ALTER ROLE aibot PASSWORD` — one statement, through the `pgvector` pod
- `minecraft-test/secret/agent-config.data.PG_DSN`
- `minecraft-test/secret/hive-credentials.data.PG_DSN`
- `minecraft/secret/agent-config.data.PG_DSN` ← **PROD WRITE. Only under an explicit (A) ruling.**

**Never in scope, under either option:**
- `secret/minecraft-rcon` (`RCON_PASSWORD`) — PROD rcon is never rotated (standing order).
- Any other credential: `MOD_API_KEY`, `RUNNER_TOKEN`/`agent-script-runner-token`,
  `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `harbor-creds`, `minio-creds`, hive credentials.
- Deleting or editing the PVC `pgvector-data-pvc`.
- Any namespace outside `minecraft-test` and `minecraft`.

---

## 2. What a DSN looks like here (so the write is reconstructable)

Measured shape, non-secret fields only:

```
postgresql://aibot:<32 chars>@pgvector.minecraft-test.svc.cluster.local:5432/<db>
```

`dsn_len` differs per holder (113 / 112 / 108) **only because the database name differs**
(`botmemory_test` / `hivemind_test` / `botmemory`). There is no `sslmode` parameter in any
of the three today. The new DSN must therefore be assembled per-holder from its **own**
database name, not copied between holders — copying the test DSN into prod would silently
point prod at `botmemory_test`.

The new password must preserve: 32 characters, URL-safe (hex is the safe choice), and
**percent-encoded** in the DSN (a hex password needs no encoding, which is one reason to
use hex).

---

## 3. Preconditions (read-only) — run and STOP unless every line passes

Every fingerprint is taken **inside the ssh command on controlplane**; the value never
crosses to this VM. Every read is length-gated, because an empty read hashes to
`e3b0c44298fc1c14` — sixteen plausible hex characters that would "pass" a naive check.

```bash
ssh controlplane 'bash -s' <<'REMOTE'
set -u
ABORT=0
check() { # ns secret field expect_len label
  local ns=$1 sec=$2 fld=$3 want=$4 label=$5
  local raw n fp
  raw=$(kubectl -n "$ns" get secret "$sec" -o jsonpath="{.data.$fld}" 2>/dev/null)
  if [ -z "$raw" ]; then echo "ABORT: $label read EMPTY"; ABORT=1; return; fi
  n=$(printf %s "$raw" | base64 -d | wc -c)
  fp=$(printf %s "$raw" | base64 -d | sha256sum | cut -c1-12)
  if [ "$n" -ne "$want" ]; then echo "ABORT: $label decoded $n bytes, expected $want"; ABORT=1; return; fi
  echo "OK   $label len=$n fp=$fp"
}
# the three DSNs, each ~108-113 bytes and carrying the same password
for t in "minecraft-test agent-config" "minecraft-test hive-credentials" "minecraft agent-config"; do
  set -- $t
  raw=$(kubectl -n "$1" get secret "$2" -o jsonpath='{.data.PG_DSN}' 2>/dev/null)
  [ -n "$raw" ] || { echo "ABORT: $1/$2 PG_DSN EMPTY"; ABORT=1; continue; }
  n=$(printf %s "$raw" | base64 -d | wc -c)
  echo "OK   $1/$2 PG_DSN len=$n"
done
# the server must be up before we touch the role
kubectl -n minecraft-test get pods -l app=pgvector -o wide || ABORT=1
[ "$ABORT" -eq 0 ] || { echo "ABORT: preconditions failed; do not proceed"; exit 1; }
echo "--- preconditions complete"
REMOTE
```

Additionally record the four current fingerprints from §0 and require they **all still
equal `d71ad15a7e8e`**. If any has drifted, this plan's premise (one password, four
places) is stale and must be re-derived before use.

---

## 4. Backup — in-cluster copies, never VM disk

The live password never reaches this VM's filesystem (same ruling as the MOD_API_KEY plan).
Copies are made wholly on controlplane and live in the cluster.

```bash
ssh controlplane 'bash -s' <<'REMOTE'
set -eu
NS=minecraft-test
for src in "agent-config pgdsn-backup-agent-config" "hive-credentials pgdsn-backup-hive-credentials"; do
  set -- $src
  SRC=$1; DST=$2
  kubectl -n $NS get secret "$SRC" -o json \
    | python3 -c 'import json,sys;o=json.load(sys.stdin);[o["metadata"].pop(k,None) for k in ("resourceVersion","uid","creationTimestamp","selfLink","immutable")];o["metadata"]["name"]=sys.argv[1];print(json.dumps(o))' "$DST" \
    | kubectl apply -f - >/dev/null
  # verify the COPY, not the source: compare whole .data, still base64, so nothing decodes
  a=$(kubectl -n $NS get secret "$SRC" -o json | python3 -c 'import json,sys,hashlib;print(hashlib.sha256(json.dumps(json.load(sys.stdin)["data"],sort_keys=True).encode()).hexdigest()[:16])')
  b=$(kubectl -n $NS get secret "$DST" -o json | python3 -c 'import json,sys,hashlib;print(hashlib.sha256(json.dumps(json.load(sys.stdin)["data"],sort_keys=True).encode()).hexdigest()[:16])')
  [ -n "$a" ] && [ "$a" = "$b" ] || { echo "ABORT: copy $DST .data differs from $SRC"; exit 1; }
  echo "$DST verified whole .data fp=$b"
done
REMOTE
```

If option (A) is ruled, **also** copy the prod secret before writing it:
`minecraft/agent-config → pgdsn-backup-agent-config-prod` (same shape). A prod write
without an in-cluster backup is not permitted.

Delete the `pgdsn-backup-*` copies at the end of the run once verification passes, and
record the deletion on the queue row.

---

## 5. Rotate (option A only)

```bash
# Generate ONCE. 16 random bytes -> 32 hex chars, matching the current length exactly.
NEW=$(openssl rand -hex 16)
# Assert before any write. An empty or short password would be written into four places
# and every consumer would fail closed -- the whole stack down, not one bot.
[ ${#NEW} -eq 32 ] || { echo "ABORT: new password not 32 chars"; unset NEW; exit 1; }

# 5a. The role. ALTER ROLE is the authoritative change; everything else follows it.
printf '%s' "$NEW" | ssh controlplane "kubectl -n minecraft-test exec -i deploy/pgvector -- \
  psql -U aibot -d postgres -v ON_ERROR_STOP=1 -c \"ALTER ROLE aibot PASSWORD '\$(cat)'\"" \
  || { echo "ABORT: ALTER ROLE failed"; unset NEW; exit 1; }

# 5b. Rebuild each DSN with ITS OWN database name. Never copy one DSN to another holder.
#     The password is hex so it needs no percent-encoding.
set_dsn() { # ns secret db
  printf '%s' "$NEW" | ssh controlplane "read -r PW; kubectl -n $1 patch secret $2 --type=merge -p \
    \"{\\\"data\\\":{\\\"PG_DSN\\\":\\\"\$(printf %s 'postgresql://aibot:'\"\$PW\"'@pgvector.minecraft-test.svc.cluster.local:5432/$3' | base64 -w0)\\\"}}\"" \
    || { echo "ABORT: patch $1/$2 failed"; return 1; }
}
set_dsn minecraft-test agent-config botmemory_test || exit 1
set_dsn minecraft-test hive-credentials hivemind_test || exit 1
set_dsn minecraft agent-config botmemory || exit 1   # PROD -- ONLY under an explicit (A) ruling
unset NEW
```

**Why a patch and not `create --dry-run=client -o yaml | apply`:** a Secret taken with
`-o yaml` carries `resourceVersion` and is rejected as stale on apply — the trap that made
run 3's rollback a silent no-op. Also note `--from-file` + `apply` has a subtlety the
runner-token work ran into: `--from-file` stores raw bytes, and `-o yaml` renders the
field base64 once; a `patch` with an explicitly base64 value has no such ambiguity.

**`read -r PW` inside the ssh command, not a shell variable on this VM**, keeps the
password out of this VM's process table and shell history.

---

## 6. Verify, restart, pass check

### 6a. All three DSNs now carry the same NEW password, and they differ from the old

```bash
ssh controlplane 'bash -s' <<'REMOTE'
set -u
for t in "minecraft-test agent-config" "minecraft-test hive-credentials" "minecraft agent-config"; do
  set -- $t
  kubectl -n "$1" get secret "$2" -o json | python3 -c '
import base64,hashlib,json,sys
from urllib.parse import urlsplit
o=json.load(sys.stdin)
raw=base64.b64decode(o["data"]["PG_DSN"],validate=True).decode()
pw=urlsplit(raw).password or ""
print("OK %s/%s len=%d pwfp=%s" % (o["metadata"]["namespace"],o["metadata"]["name"],len(pw),hashlib.sha256(pw.encode()).hexdigest()[:12]))
' "$1" "$2"
done
REMOTE
```

Expect **three identical** `pwfp` values, **all different from `d71ad15a7e8e`**.

### 6b. Restart every consumer — none re-reads its DSN

| workload | namespace | mechanism | notes |
|---|---|---|---|
| `deploy/aibot-agent-test` | minecraft-test | `envFrom secret/agent-config` | reads at import |
| `deploy/hive-service` | minecraft-test | `env PG_DSN <- secret/hive-credentials` | reads at import |
| `deploy/aibot-agent` | **minecraft** | `envFrom secret/agent-config` | reads at import; **only under (A)** |

`pgvector` is **not** restarted: it is the server, and `ALTER ROLE` takes effect
immediately for new connections.

```bash
for t in "minecraft-test aibot-agent-test" "minecraft-test hive-service"; do
  set -- $t
  ssh controlplane "kubectl -n $1 rollout restart deploy/$2" || echo "ABORT: restart $2 failed"
done
ssh controlplane "kubectl -n minecraft-test rollout status deploy/aibot-agent-test --timeout=180s"
ssh controlplane "kubectl -n minecraft-test rollout status deploy/hive-service --timeout=180s"
# under (A) only:
# ssh controlplane "kubectl -n minecraft rollout restart deploy/aibot-agent"
# ssh controlplane "kubectl -n minecraft rollout status deploy/aibot-agent --timeout=180s"
```

### 6c. A stale or half-rotated consumer must 401, not half-work

A consumer still on the old password fails to connect at all, which is the *expected*
failure if a restart was missed. It must not be mistaken for success: check logs for
connection errors rather than assuming "pod Running" means "database reachable".

```bash
ssh controlplane "kubectl -n minecraft-test logs deploy/aibot-agent-test --tail=100" | grep -ciE 'password authentication failed|FATAL:  password' 
ssh controlplane "kubectl -n minecraft-test logs deploy/hive-service --tail=100" | grep -ciE 'password authentication failed|FATAL:  password'
```

**Expect `0` from both.** A non-zero count means that consumer is on the old password.

### 6d. The pass criterion — the new password actually authenticates

```bash
ssh controlplane 'bash -s' <<'REMOTE'
# Prove the role authenticates with the NEW password by making the server accept it,
# without printing it: connect through the pgvector pod using the DSN it does not hold.
for t in "minecraft-test agent-config botmemory_test" "minecraft-test hive-credentials hivemind_test"; do
  set -- $t
  kubectl -n "$1" get secret "$2" -o jsonpath='{.data.PG_DSN}' | base64 -d > /tmp/pgdsn.check
  out=$(kubectl -n minecraft-test exec -i deploy/pgvector -- psql "$(cat /tmp/pgdsn.check)" -tAc 'select 1' 2>&1 | tail -1)
  rm -f /tmp/pgdsn.check
  echo "$1/$2 -> $out"
done
REMOTE
```

**Expect `1` for both.** Anything else (including no output) is a FAIL — an empty result
is the empty-read trap again.

**A second, independent check that the OLD password is now rejected**, from the backup
copy, proves the rotation took rather than merely that *a* connection works. Expect
`password authentication failed`.

**Pass requires:** 6a three identical new fingerprints ≠ old; 6b all restarts complete;
6c zero password-failure lines; 6d `1` from both DSNs and old password rejected.

---

## 7. If option (B) is chosen instead

Deltas only — the rest of this plan stands if the DSNs are pointed at the new role:

1. Do **not** run `ALTER ROLE aibot`. Instead create `aibot_test` with a new password and
   `GRANT` it the same privileges on `botmemory_test` and `hivemind_test` as `aibot` has.
   Derive the grant set from `\du` / `information_schema.role_table_grants` for `aibot`
   at execution time — do not guess it.
2. Update **only** the two TEST DSNs, with `user=aibot_test`.
3. **Do not touch `minecraft/agent-config`** — prod keeps `aibot`. This is the whole
   benefit of (B).
4. Restart only the two TEST consumers.
5. Verify as 6a–6d, but expect the **prod** fingerprint to stay `d71ad15a7e8e`, and state
   that explicitly as the check that prod was not disturbed.
6. Record on the row that the stack now has **two roles** where it had one, and that
   `aibot` is exercised only by prod from now on.

---

## 8. Rollback

Trigger: any precondition failure, any ABORT in §5, 6a fingerprints differ, a rollout
fails, 6c non-zero, or 6d not `1`.

```bash
set -euo pipefail
# Restore BOTH secrets before restarting EITHER pod: a restart between restores 401s and
# looks like a failed rollback.
for pair in "pgdsn-backup-agent-config agent-config" "pgdsn-backup-hive-credentials hive-credentials"; do
  set -- $pair
  ssh controlplane "kubectl -n minecraft-test get secret $1 -o json" \
    | python3 -c 'import json,sys;o=json.load(sys.stdin);o["metadata"]["name"]=sys.argv[1];[o["metadata"].pop(k,None) for k in ("resourceVersion","uid","creationTimestamp","selfLink","immutable")];print(json.dumps(o))' "$2" \
    | ssh controlplane "kubectl -n minecraft-test apply -f -" \
    || { echo "ABORT: restore of $2 failed -- do NOT restart consumers"; exit 1; }
done
# The role password is NOT restored by a Secret apply: the database still holds the new one.
# Roll it back explicitly, from the backup DSN, or both consumers stay broken.
ssh controlplane 'bash -s' <<'REMOTE'
set -eu
kubectl -n minecraft-test get secret pgdsn-backup-agent-config -o jsonpath='{.data.PG_DSN}' | base64 -d > /tmp/pgdsn.rb
OLD=$(python3 -c 'from urllib.parse import urlsplit;print(urlsplit(open("/tmp/pgdsn.rb").read()).password)')
rm -f /tmp/pgdsn.rb
kubectl -n minecraft-test exec deploy/pgvector -- psql -U aibot -d postgres -v ON_ERROR_STOP=1 -c "ALTER ROLE aibot PASSWORD '$OLD'"
REMOTE
for t in "minecraft-test aibot-agent-test" "minecraft-test hive-service"; do
  set -- $t
  ssh controlplane "kubectl -n $1 rollout restart deploy/$2" || exit 1
done
```

Then re-run §3 and require all four fingerprints to return to `d71ad15a7e8e`. Under (A),
prod's secret must be restored too.

**The rollback itself must be rehearsed** before this plan is executed: the ALTER ROLE
from a backup DSN has the same quoting hazards as the forward direction, and a rollback
that has never run is not a rollback.

---

## 9. Verification record (filled when this executes)

- BEFORE fingerprints: `d71ad15a7e8e` ×4 (measured 2026-11-22) — _reconfirm at run time_
- AFTER fingerprints: _pending_
- 6c password-failure lines: _pending_ · 6d new-DSN `1`: _pending_ · old rejected: _pending_
- rollback: rehearsed? _pending_

---

## 10. What this plan deliberately does not do

- **It does not execute.** No secret was written, created, deleted or read in producing it.
- **It does not rotate prod** unless option (A) is explicitly ruled. §0.1 is the decision.
- **It does not rotate** `RCON_PASSWORD`, `MOD_API_KEY`, `RUNNER_TOKEN`, `DEEPSEEK_API_KEY`,
  `OPENAI_API_KEY`, `harbor-creds`, `minio-creds`, or hive credentials.
- **It does not touch the PVC** `pgvector-data-pvc`, and therefore cannot recover a
  database whose data is lost — it changes one role's password, nothing else.
- **It cannot prove no other copy exists.** This sweep covered Secrets in two namespaces.
  It cannot see a copy in an image layer, a config file on a host, or another project's
  namespace. It is a floor, not a proof.
- **It cannot find a consumer that reads PG_DSN without naming it** — e.g. a workload that
  receives it inside a mounted file the audit does not parse. The audit covered
  `env`/`envFrom` on Deployments/StatefulSets/CronJobs only; a Pod created outside a
  controller was not enumerated.

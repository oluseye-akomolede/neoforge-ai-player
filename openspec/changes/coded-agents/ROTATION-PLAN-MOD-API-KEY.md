# Rotation plan — `MOD_API_KEY` / `AIPLAYER_API_KEY`

**Status:** awaiting reviewer PASS, then lead OK. **Not executed.**
**Date:** 2026-11-13 · **Cluster:** TEST (`minecraft-test`) only. PROD is out of scope and untouched.

## Why

During the M2 run-5 debugging a live `MOD_API_KEY` value reached the builder seat's
transcript (a `sed` redaction ran after `env`'s output had already been printed). The
lead ruled: rotate. The value is compromised; assume the transcript is readable.

## Holder list — established from source and manifests only, no values read

The same secret value is held in **two** places under **two different names**. This is
what makes it a two-sided rotation.

| # | Side | Holder | Citation (file:line) |
|---|---|---|---|
| 1 | Agent (client) | `secret/agent-config` → key `MOD_API_KEY` | `deploy/agent-deployment.yaml:24-26` (`envFrom: secretRef: agent-config` — the whole secret, so no per-key `secretKeyRef` exists); read at `agent/config.py:8` (`os.getenv("MOD_API_KEY", "")`) |
| 2 | Server (mod) | `secret/mod-api-key` → key `api-key` | mc-server container env `AIPLAYER_API_KEY` is a `secretKeyRef` to `mod-api-key`/`api-key`; read at `src/main/java/com/sigmastrain/aiplayermod/AIPlayerMod.java:69-70` (`-Daiplayermod.api.key` then `System.getenv("AIPLAYER_API_KEY")`) |

**The mod validates server-side, so one side alone breaks everything:**

`src/main/java/com/sigmastrain/aiplayermod/api/HttpApiServer.java:148-150` —
`if (apiKey == null || apiKey.isEmpty()) return true;` then compares the `X-Api-Key`
header and returns **401 Invalid API key** on mismatch.

**Current state — verified by fingerprint, not by value:**

| holder | sha256 prefix | length |
|---|---|---|
| `agent-config`/`MOD_API_KEY` | `3b0a18f8580cad25…` | 40 |
| `mod-api-key`/`api-key` | `3b0a18f8580cad25…` | 40 |

Identical. They must stay identical across the rotation.

### Holder-list scope limit (stated, not glossed)

This list covers the two holders reachable from this repo's manifests and the live TEST
objects. It does **not** cover: (a) any other cluster or namespace — PROD was not
searched, by standing order; (b) copies inside an image layer, an `env` file baked into
an image, or a developer machine. If the reviewer knows of another holder, it belongs
in this table before the script runs.

## The change

One new value, **generated inside the script**, written to both holders in one atomic
operation, then both pods restarted. The operator never types or sees the value: it is
generated, piped to `kubectl`, and only its fingerprint is printed.

### Step 0 — preconditions (read-only)

```bash
# both pods healthy before we start
ssh controlplane "kubectl -n minecraft-test get pods -l tier=test -o wide"
# record the BEFORE fingerprints so we can prove the change afterwards
for s in "agent-config MOD_API_KEY" "mod-api-key api-key"; do
  set -- $s
  ssh controlplane "kubectl -n minecraft-test get secret $1 -o jsonpath='{.data.$2}'" \
    | base64 -d | sha256sum | cut -c1-16
done
```

Expect both to print `3b0a18f8580cad25`. If they differ, **stop** — the premise of this
plan (one value in two places) is wrong and must be re-derived.

### Step 1 — backup both secrets (values stay out of the transcript)

```bash
D=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p evidence/rotation-$D
ssh controlplane "kubectl -n minecraft-test get secret agent-config -o yaml"   > evidence/rotation-$D/agent-config.before.yaml
ssh controlplane "kubectl -n minecraft-test get secret mod-api-key  -o yaml"   > evidence/rotation-$D/mod-api-key.before.yaml
# these files contain the OLD value; they are evidence, not to be committed.
wc -c evidence/rotation-$D/*.yaml
```

**Both backup files must be treated as secret material: never commit, never paste.**
They are the rollback source only.

### Step 2 — rotate: generate once, write to both

```bash
NEW=$(openssl rand -hex 20)   # 40 hex chars, matching the current length
# verify length before writing: the mod compares with .equals, so any length works,
# but keeping 40 leaves the shape unchanged.
printf '%s' "$NEW" | wc -c    # expect 40

printf '%s' "$NEW" | ssh controlplane \
  "kubectl -n minecraft-test patch secret mod-api-key --type=merge -p \
   \"{\\\"data\\\":{\\\"api-key\\\":\\\"\$(base64 -w0)\\\"}}\""

printf '%s' "$NEW" | ssh controlplane \
  "kubectl -n minecraft-test patch secret agent-config --type=merge -p \
   \"{\\\"data\\\":{\\\"MOD_API_KEY\\\":\\\"\$(base64 -w0)\\\"}}\""

unset NEW
```

**Why a patch and not `create --dry-run=client -o yaml | apply`:** `apply` on a secret
taken with `-o yaml` carries `resourceVersion` and rejects as stale — the exact trap that
made run 3's rollback a silent no-op (`openspec/changes/coded-agents/M2-PLAN.md`, and
memory: *a yaml backup is not re-appliable*).

### Step 3 — verify both holders changed together

```bash
for s in "agent-config MOD_API_KEY" "mod-api-key api-key"; do
  set -- $s
  ssh controlplane "kubectl -n minecraft-test get secret $1 -o jsonpath='{.data.$2}'" \
    | base64 -d | sha256sum | cut -c1-16
done
```

Expect two **identical** new fingerprints, **different** from `3b0a18f8580cad25`.
If they differ from each other: **stop and roll back** — a half-rotated pair 401s.

### Step 4 — restart both pods

The agent reads `MOD_API_KEY` at import (`agent/config.py:8`), and the mod reads
`AIPLAYER_API_KEY` at startup (`AIPlayerMod.java:69-70`) and holds it in the
`HttpApiServer` field (`:60`) — **neither re-reads**, so both need a restart.

```bash
ssh controlplane "kubectl -n minecraft-test rollout restart deploy/aibot-agent-test"
ssh controlplane "kubectl -n minecraft-test rollout restart deploy/minecraft-test-server"
ssh controlplane "kubectl -n minecraft-test rollout status deploy/aibot-agent-test --timeout=180s"
ssh controlplane "kubectl -n minecraft-test rollout status deploy/minecraft-test-server --timeout=300s"
```

### Step 5 — the pass criterion: new key works, OLD key 401s

(a) **New key works** — an authenticated call from inside the agent pod succeeds:

```bash
P=$(ssh controlplane "kubectl -n minecraft-test get pods -l app=aibot-agent -o jsonpath='{.items[0].metadata.name}'")
ssh controlplane "kubectl -n minecraft-test exec $P -c agent -- python3 -c '
import os, json, urllib.request
req = urllib.request.Request(os.environ[\"MOD_API_URL\"] + \"/bot/Scout\",
    headers={\"X-Api-Key\": os.environ[\"MOD_API_KEY\"]})
d = json.loads(urllib.request.urlopen(req, timeout=10).read())
print(\"ok, Scout at\", d[\"position\"])'"
```

(b) **Old key is rejected** — the same call with the OLD value must return 401. The old
value is decoded from the backup on the VM and piped **straight through** to Python on
the pod's stdin. It is never assigned to a shell variable, because a shell variable
would consume the stream before `exec -i` sees it (verified: `exec -i` passes 9/9 bytes;
an intermediate `read K` consumes them and leaves Python with an empty key, which would
make this check pass for the wrong reason).

```bash
python3 -c "
import yaml,base64,sys
d=yaml.safe_load(open('evidence/rotation-$D/agent-config.before.yaml'))
sys.stdout.write(base64.b64decode(d['data']['MOD_API_KEY']).decode())" \
| ssh controlplane "kubectl -n minecraft-test exec -i $P -c agent -- python3 -c '
import os, sys, urllib.error, urllib.request
key = sys.stdin.read().strip()
assert key, \"no old key on stdin -- this check would pass for the wrong reason\"
req = urllib.request.Request(os.environ[\"MOD_API_URL\"] + \"/bot/Scout\",
    headers={\"X-Api-Key\": key})
try:
    urllib.request.urlopen(req, timeout=10); print(\"UNEXPECTED 200 -- rotation did not take\")
except urllib.error.HTTPError as e: print(\"status\", e.code)'"
```

The `assert key` is load-bearing: without it an empty stdin would produce
`X-Api-Key: `, and whether that 401s depends on the mod's empty-key bypass at
`HttpApiServer.java:148` (`if (apiKey == null || apiKey.isEmpty()) return true;`) —
a check that could pass while testing nothing.

**Expect `status 401`.** A 200 here means the rotation did not take effect — the mod is
still comparing the old value, i.e. its pod did not restart or it did not re-read.

## Rollback

Roll back if **any** of: step 3's fingerprints differ from each other, step 4's rollouts
fail, step 5(a) fails, or step 5(b) returns 200.

```bash
D=<the rotation stamp>
# restore both secrets from backup, stripping server-side fields so the apply is not stale
for f in agent-config mod-api-key; do
  kubectl create --dry-run=client -o yaml -f evidence/rotation-$D/$f.before.yaml \
    | python3 -c "
import sys,yaml
d=yaml.safe_load(sys.stdin)
for k in ('resourceVersion','uid','creationTimestamp','selfLink'): d['metadata'].pop(k,None)
print(yaml.safe_dump(d))" \
    | ssh controlplane "kubectl -n minecraft-test apply -f -"
done
ssh controlplane "kubectl -n minecraft-test rollout restart deploy/aibot-agent-test"
ssh controlplane "kubectl -n minecraft-test rollout restart deploy/minecraft-test-server"
```

Then re-run step 0's fingerprints: both must return to `3b0a18f8580cad25`.

**Rollback ordering note:** restore **both** secrets before restarting either pod. A
restart between the two restores will 401 and look like a failed rollback.

## Verification record (to be filled by the queue item when this executes)

- BEFORE fingerprints: `3b0a18f8580cad25…` ×2 (verified 2026-11-13)
- AFTER fingerprints: _pending_
- new key works: _pending_ · old key 401: _pending_
- rollback command: above

## What this plan deliberately does not do

- It does not touch `secret/minecraft-rcon` (`RCON_PASSWORD`) or any other secret. The
  standing order is that PROD rcon is never rotated; TEST rcon is not in scope here either.
- It does not change the mod's key **length** or format, so nothing depends on the shape.
- It does not rotate `RUNNER_TOKEN` (`agent-script-runner-token`), `DEEPSEEK_API_KEY`,
  `OPENAI_API_KEY`, `PG_DSN`, `harbor-creds`, `minio-creds`, or the hive credentials.
  They are separate credentials with separate holders; folding them in would make one
  failure ambiguous.

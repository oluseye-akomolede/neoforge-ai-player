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
| `deploy/l2-mcp` env `MOD_API_KEY` ← `secretKeyRef` `mod-api-key`/`api-key` | `3b0a18f8580cad25…` | 40 |

Identical. They must stay identical across the rotation.

**Holder 3 — `l2-mcp` (reviewer finding, independently re-verified).** Not an obvious
third holder, and I missed it. `deploy/l2-mcp` takes `MOD_API_KEY` from
`secretKeyRef: mod-api-key/api-key`; `l2-mcp/app/item_registry.py:41` reads it and `:78`
sends it as `X-Api-Key`. Its `MOD_API_URL` is empty in the live env, but the code default
(`:40`) is `http://minecraft-test-server:3100` — the same key-gated port. **It
authenticates with this key today.**

Its failure mode is why it cannot be left out: `load()` catches `Exception` and falls back
to legacy naming at `WARNING` (`:98`), with the result cached for
`REFRESH_SECONDS = 3600` (`:42`). A missed holder is therefore a **silently degraded L2
item registry for up to an hour**, with nothing in the pass criterion pointing at it.

Note the source differs from holders 1–2: this is not a second copy of the value, it is a
**second consumer of the same Secret**. So it needs no separate write (the `mod-api-key`
patch covers it) but it **does** need its own restart, because it reads at import.

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

### Step 0a — fingerprint sweep, before anything else (lead ruling 3)

The holder table was built by hand and **missed a third holder** until the reviewer found
it. A sweep finds holders mechanically instead of by luck. It prints only
namespace/name/key for matches — never a value.

```bash
ssh controlplane 'bash -s' <<'REMOTE'
set -u
WANT=3b0a18f8580cad25
for ns in minecraft-test minecraft; do
  for kind in secret configmap; do
    for obj in $(kubectl -n $ns get $kind -o name 2>/dev/null); do
      kubectl -n $ns get $obj -o json 2>/dev/null | python3 -c '
import base64,hashlib,json,sys
o=json.load(sys.stdin); want=sys.argv[1]
ns=o["metadata"]["namespace"]; nm=o["metadata"]["name"]
scanned=skipped=0
for k,v in (o.get("data") or {}).items():
    # ConfigMap values are plain strings and may be non-ASCII; only Secrets are base64.
    # An unparseable key must be COUNTED, not skipped: a crash mid-object leaves the
    # remaining keys unchecked while the sweep still prints "complete".
    if o.get("kind") == "Secret":
        try: raw = base64.b64decode(v, validate=True)
        except Exception: skipped += 1; continue
    else:
        raw = str(v).encode("utf-8", "replace")
    scanned += 1
    if hashlib.sha256(raw).hexdigest().startswith(want):
        print(f"HIT  {ns}/{nm}/{k}")
print(f"     {ns}/{nm}: scanned={scanned} unparsed={skipped}") if skipped else None
' "$WANT"
    done
  done
done
echo "--- sweep complete"
REMOTE
```

**Requires `unparsed=0` on every line.** A non-zero count means part of that object was not
checked, so "no hit" is not a clean result for it.

Scope: **`minecraft-test` and our prod namespace (`minecraft`) only** — no other projects'
namespaces (lead ruling 3). Every hit goes in the holder table, even if it is one we think
is inert.

**Prod is swept to prove it is unaffected, not because a hit is expected.** Measured
11-13: both hits are in `minecraft-test`; `minecraft` has none. So this rotation does not
touch prod, and no prod object may appear in any *write* step — `minecraft/aibot-agent`
and `minecraft/minecraft-server` are out of scope by standing order.

A clean sweep is *not* proof of completeness: it cannot see a copy that lives outside
these namespaces, in an image layer, or in a config file. It is a floor, and the table
must say so.

**It also cannot find a consumer.** Measured 11-13: the sweep returns exactly two hits —
`minecraft-test/agent-config/MOD_API_KEY` and `minecraft-test/mod-api-key/api-key` — and
**nothing in `minecraft` (prod)**. Holder 3 (`l2-mcp`) does not appear, because it stores
no copy of the value: it reads `mod-api-key` at import. A value fingerprint finds *copies*,
never *readers*. That is exactly how this plan missed l2-mcp the first time, and no sweep
would have caught it — only auditing env/`envFrom` per workload does. Do both.

### Step 0b — consumer audit, per workload (the check that finds holder 3)

A value sweep finds copies; only an env audit finds **readers**. Measured 11-13 across both
namespaces, deployments only:

```
minecraft-test/aibot-agent-test      envFrom secret agent-config
minecraft-test/l2-mcp                env MOD_API_KEY       <- mod-api-key/api-key
minecraft-test/minecraft-test-server env AIPLAYER_API_KEY  <- mod-api-key/api-key
minecraft/aibot-agent                envFrom secret agent-config             (PROD, out of scope)
minecraft/minecraft-server           env AIPLAYER_API_KEY <- mod-api-key/api-key (PROD, out of scope)
```

Three TEST consumers (the holder table) and two PROD consumers this plan must not touch.
The PROD pair read different Secret objects, and the sweep found no copy of this value in
`minecraft`, so rotating the TEST value does not reach them.

Repeat before running; **any new TEST consumer is a holder** — it needs a restart even when
it needs no write.

### Step 0c — preconditions (read-only)

```bash
# both pods healthy before we start
ssh controlplane "kubectl -n minecraft-test get pods -l tier=test -o wide"
# record the BEFORE fingerprints of ALL THREE holders so we can prove the change afterwards
for s in "agent-config MOD_API_KEY" "mod-api-key api-key"; do
  set -- $s
  ssh controlplane "kubectl -n minecraft-test get secret $1 -o jsonpath='{.data.$2}'" \
    | base64 -d | sha256sum | cut -c1-16
done
# holder 3 reads the same Secret, but must be fingerprinted at its OWN consumer, or a
# deployment pointing at a different secret would look identical to us
ssh controlplane "kubectl -n minecraft-test exec deploy/l2-mcp -- printenv MOD_API_KEY" \
  | sha256sum | cut -c1-16
```

**Compare three ways, not two** (reviewer finding): all three lines must agree, and step 0
must **stop unless all three agree**. Comparing only two would let l2-mcp already be on a
different value — in which case a successful rotation would still leave it broken and this
run would have caused it.

Expect all three to print `3b0a18f8580cad25`. If any differ, **stop** — the premise of
this plan (one value in three places) is wrong and must be re-derived.

### Step 1 — back up both secrets as in-cluster copies (lead ruling 1)

**The old value never touches VM disk.** An earlier draft of this plan redirected
`kubectl get secret -o yaml` into `evidence/…yaml`, which put the live key on this VM's
filesystem and read it back for rollback. That is forbidden: the backups are made by a
script that runs **wholly on controlplane**, and the copies live **in the cluster**.

**On the objection that this makes the rollback weaker (reviewer, 05:42Z).** The reviewer
argued the old value must stay on VM disk: *"a rollback from a secret you kept no copy of
is not a rollback"*, and fingerprint-only would make 5(b) unperformable. The concern is
right; the remedy is not the disk. An **in-cluster copy** is a full copy — it holds the
value, it restores identically, and it is readable for the old-key check. Verified:

```
ssh controlplane "kubectl -n minecraft-test get secret mod-api-key \
  -o jsonpath='{.data.api-key}' | base64 -d | wc -c"      → 40
```

So 5(b) stays performable and the rollback stays real, with no plaintext credential on a
shared VM disk. The lead's ruling governs here (security boundary, and the lead sets it);
this plan meets the ruling without losing what the reviewer correctly demanded. If the
lead would rather have a disk copy plus `shred -u`, that is a one-line change to this step.

```bash
# runs entirely on controlplane; nothing is written to this VM and nothing reaches stdout
ssh controlplane 'bash -s' <<'REMOTE'
set -eu
NS=minecraft-test
for src in "agent-config MOD_API_KEY rot-agent-config" "mod-api-key api-key rot-mod-api-key"; do
  set -- $src
  # copy the whole Secret, then rename it; never decode a value here
  kubectl -n $NS get secret "$1" -o json \
    | python3 -c 'import json,sys;o=json.load(sys.stdin);o["metadata"].pop("resourceVersion",None);o["metadata"].pop("uid",None);o["metadata"].pop("creationTimestamp",None);o["metadata"]["name"]=sys.argv[1];print(json.dumps(o))' "$3" \
    | kubectl apply -f -
done
# confirm the copies exist and are non-empty, WITHOUT printing values
kubectl -n $NS get secret rot-agent-config rot-mod-api-key -o name
REMOTE
```

The rollback and the old-key 401 check both read from `rot-agent-config` /
`rot-mod-api-key`, never from a VM file.

**Delete the copies at the end of the run** once verification passes, and record the
deletion on the queue row (lead ruling 1):

```bash
ssh controlplane "kubectl -n minecraft-test delete secret rot-agent-config rot-mod-api-key"
```

### Step 2 — rotate: generate once, write to both

```bash
NEW=$(openssl rand -hex 20)   # 40 hex chars, matching the current length
# ASSERT before writing either holder (lead ruling 2a): HttpApiServer.java:148 returns
# true for EVERY request when the configured key is empty, so an empty or short write
# would silently OPEN the API. Generate must never produce one; assert it anyway.
printf '%s' "$NEW" | wc -c | grep -qx 40 || { echo "ABORT: new key not 40 chars"; unset NEW; exit 1; }
[ -n "$NEW" ] || { echo "ABORT: new key empty"; exit 1; }

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

### Step 4 — restart all three consumers

The agent reads `MOD_API_KEY` at import (`agent/config.py:8`), the mod reads
`AIPLAYER_API_KEY` at startup (`AIPlayerMod.java:69-70`) and holds it in the
`HttpApiServer` field (`:60`), and `l2-mcp` reads it at import
(`l2-mcp/app/item_registry.py:41`) — **none of the three re-reads**, so all need a restart.
`l2-mcp` needs no separate write (it consumes the same `mod-api-key` Secret) but omitting
its restart leaves it on the old value for up to an hour without any error.

```bash
for d in aibot-agent-test minecraft-test-server l2-mcp; do
  ssh controlplane "kubectl -n minecraft-test rollout restart deploy/$d"
done
ssh controlplane "kubectl -n minecraft-test rollout status deploy/aibot-agent-test --timeout=180s"
ssh controlplane "kubectl -n minecraft-test rollout status deploy/minecraft-test-server --timeout=300s"
ssh controlplane "kubectl -n minecraft-test rollout status deploy/l2-mcp --timeout=180s"
```

**Confirm l2-mcp actually reloaded (reviewer's optional, taken).** Its failure is silent
by construction (`load()` catches and warns at `:98`), so the positive signal is worth one
grep — it distinguishes "restarted and loaded" from "restarted and fell back":

```bash
ssh controlplane "kubectl -n minecraft-test logs deploy/l2-mcp --tail=200" | grep -i 'item registry loaded'
```

Expect a line naming an item count. Absence means it fell back to legacy naming — not a
401, but a degraded registry this rotation is meant to leave healthy.

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
value is read from the in-cluster copy `rot-agent-config` and piped **straight through**
to Python on the pod's stdin. It is never assigned to a shell variable, because a shell
variable would consume the stream before `exec -i` sees it (verified: `exec -i` passes
9/9 bytes; an intermediate `read K` consumes them and leaves Python with an empty key,
which would make this check pass for the wrong reason).

```bash
ssh controlplane "kubectl -n minecraft-test get secret rot-agent-config \
  -o jsonpath='{.data.MOD_API_KEY}' | base64 -d" \
| ssh controlplane "kubectl -n minecraft-test exec -i $P -c agent -- python3 -c '
import os, sys, urllib.error, urllib.request
key = sys.stdin.read().strip()
assert key, \"no old key on stdin -- this check would pass for the wrong reason\"
req = urllib.request.Request(os.environ[\"MOD_API_URL\"] + \"/bot/Scout\",
    headers={\"X-Api-Key\": key})
try:
    urllib.request.urlopen(req, timeout=10); print(\"UNEXPECTED 200 -- rotation did not take\")
except urllib.error.HTTPError as e: print(\"old key -> status\", e.code)'"
```

**Expect `old key -> status 401`.**

(c) **Wrong key is rejected** — a key that was never valid (elsewhere fixed (b) alone
could pass if the mod were down rather than comparing):

```bash
ssh controlplane "kubectl -n minecraft-test exec $P -c agent -- python3 -c '
import os, urllib.error, urllib.request
req = urllib.request.Request(os.environ[\"MOD_API_URL\"] + \"/bot/Scout\",
    headers={\"X-Api-Key\": \"0\" * 40})
try:
    urllib.request.urlopen(req, timeout=10); print(\"WRONG KEY 200 -- auth is not enforced\")
except urllib.error.HTTPError as e: print(\"wrong key -> status\", e.code)'"
```

**Expect `wrong key -> status 401`.**

(d) **Empty key is rejected — the open-server check (lead ruling 2b).** This is the
negative that (b) and (c) cannot substitute for. `HttpApiServer.java:148` returns `true`
for every request when the *configured* key is empty, so if the patch wrote an empty
value, the server accepts everything: (b) and (c) would then both print **200**, and a
naive reading of "the new key works" would call that a pass. Asserting 401 on both a
wrong key and an empty header proves auth is *enforced*, not merely that some key works.

```bash
ssh controlplane "kubectl -n minecraft-test exec $P -c agent -- python3 -c '
import os, urllib.error, urllib.request
req = urllib.request.Request(os.environ[\"MOD_API_URL\"] + \"/bot/Scout\",
    headers={\"X-Api-Key\": \"\"})
try:
    urllib.request.urlopen(req, timeout=10); print(\"EMPTY KEY 200 -- AUTH IS OFF, API IS OPEN\")
except urllib.error.HTTPError as e: print(\"empty key -> status\", e.code)'"
```

**Expect `empty key -> status 401`.** A 200 here is the worst outcome in this plan: it
means the mod is running with auth disabled and every caller is trusted. **Stop and roll
back immediately**; do not continue to cleanup.

**Pass requires all four:** new key 200 (a), old key 401 (b), wrong key 401 (c), empty
key 401 (d).

## Rollback

Roll back if **any** of: step 0c's three fingerprints disagree with each other, step 3's
fingerprints differ from each other, step 4's rollouts fail, step 5(a) fails, or any of
5(b)/(c)/(d) returns **200**.

Restore from the **in-cluster copies** made in step 1 — never from a VM file (lead ruling 1):

```bash
for pair in "rot-agent-config agent-config" "rot-mod-api-key mod-api-key"; do
  set -- $pair
  ssh controlplane "kubectl -n minecraft-test get secret $1 -o json" \
    | python3 -c '
import json,sys
o=json.load(sys.stdin)
o["metadata"]["name"]=sys.argv[1]
for k in ("resourceVersion","uid","creationTimestamp","selfLink"): o["metadata"].pop(k,None)
print(json.dumps(o))' "$2" \
    | ssh controlplane "kubectl -n minecraft-test apply -f -"
done
# strip server-side fields or the apply is rejected as stale -- the run-3 trap
for d in aibot-agent-test minecraft-test-server l2-mcp; do
  ssh controlplane "kubectl -n minecraft-test rollout restart deploy/$d"
done
```

Then re-run step 0c's fingerprints: all three must return to `3b0a18f8580cad25`.

### Rollback chain tested, not assumed

The restore shape was exercised end-to-end against a throwaway secret (`rt-check`,
created and deleted within the test): a YAML carrying `resourceVersion`, `uid` and
`creationTimestamp` → strip those three → `ssh controlplane "kubectl apply -f -"` →
`secret/rt-check created` → value read back correctly. This is the fix for the trap that
made run 3's rollback a rejected no-op, and `apply -f -` does read stdin through `ssh`
(verified, because an intermediate consumer is exactly what broke the old-key check).

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

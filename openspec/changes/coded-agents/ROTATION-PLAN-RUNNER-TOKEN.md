# Rotation plan — runner token key `minecraft`

**Status:** awaiting reviewer PASS, then lead OK, then the LEAD runs it. **Not executed.**
**Date:** 2026-11-13 · **Cluster:** TEST (`minecraft-test`) only. PROD is out of scope and untouched.
**Queue:** `qitem-20261113110946-1b676f5be3694dd6`

## Why

At ~11:08Z the reviewer printed the live `RUNNER_TOKEN` from agent pod
`aibot-agent-test-6f76986444-vqs44` into its seat transcript. Assume that transcript is
readable. The `minecraft` token is compromised and must be replaced.

This plan is modelled on `ROTATION-PLAN-MOD-API-KEY.md` (`ad229b3`), and it inherits that
plan's hard-won corrections rather than its early drafts: fingerprints computed on
controlplane, an exact old-value fingerprint comparison (**not** a length check), and
every guard as code that exits non-zero.

## Scope — and the two traps in it

The exposure is **one key of one Secret**:

| Object | Key | Consumer | Citation |
|---|---|---|---|
| `minecraft-test/secret/agent-script-runner-token` | `minecraft` | runner env `RUNNER_TOKEN_MINECRAFT` | live `deploy/agent-script-runner`, container `runner` |
| same Secret, same key | `minecraft` | agent env `RUNNER_TOKEN` | live `deploy/aibot-agent-test`, container `agent` |

Two consumers, **one write**, two restarts. Both read the same Secret key, so one patch
covers both and the row's "restart ONCE" is achievable for the runner.

**Trap 1 — the `cardgame` key lives in the same Secret.** Measured 11-13 on
`minecraft-test/agent-script-runner-token`: keys are exactly `['cardgame', 'minecraft']`,
64 bytes each, fingerprints `67e11daedad1c013` (`cardgame`) and `92a0dd82e0748559`
(`minecraft`). A `--type=merge` patch on `.data.minecraft` is key-scoped and leaves
`cardgame` alone; an `apply` of a whole `.data` object would **silently drop it**, and the
runner would then fail to start.

**The mechanism, corrected (reviewer, 11-13 — my first draft said "throws at
`main.js:118`", which is wrong).** There are two layers and only the first fires:

1. **The kubelet refuses to create the container.** Neither `secretKeyRef` is `optional`
   (measured on the live Deployment: both absent), so with `cardgame` gone the container
   comes up as `CreateContainerConfigError` and **never runs**.
2. **`tokensFromEnv` would NOT have caught it** (`agent-script-runner/src/main.js:113-126`).
   The loop iterates `process.env` entries matching `RUNNER_TOKEN_*`, so a dropped key is
   simply never seen: `size === 0` is false while `minecraft` remains, and the function
   returns a one-game map. Had the key been `optional`, the runner would have started
   silently without cardgame and refused its every call at request time.

So the failure is loud because of the kubelet, not because of the code. That makes
`--type=merge` scoping the thing to get right — nothing downstream would have caught it.

**Trap 2 — `cardgame`'s own copy is a DIFFERENT object and is out of scope.** The row
names it as `cardgame/match-server`, key `token`. Measured 11-13: `cardgame` namespace
has its own Secret `agent-script-runner-token` with key `token`, and `cardgame/match-server`
takes `AGENT_SCRIPT_RUNNER_TOKEN` from it. That is **not** the key we rotate and **not**
the same Secret. It must not appear in any write step. The `cardgame` key *inside* the
`minecraft-test` Secret is a third and different thing again: it is the token our runner
uses to authenticate cardgame's calls into *our* runner.

So: three things called "cardgame", only one of which this plan reads (to prove it
unchanged) and none of which it writes.

## Holder list — and its stated limit

Established from live object specs and source, **no values read**:

| # | Side | Holder | How it reads it |
|---|---|---|---|
| 1 | Runner (server) | `deploy/agent-script-runner`, container `runner` | env `RUNNER_TOKEN_MINECRAFT` ← `secretKeyRef` `agent-script-runner-token`/`minecraft`, read at start (`main.js:113-126`) |
| 2 | Agent (client) | `deploy/aibot-agent-test`, container `agent` | env `RUNNER_TOKEN` ← `secretKeyRef` `agent-script-runner-token`/`minecraft`, read at import (`agent/config.py:22`, consumed at `agent/script_tick.py:51-52`) |

**Current state — verified by fingerprint, not by value** (hashed on controlplane; the
agent's read used `printf %s` **in the pod**, never `printenv`):

| holder | sha256 prefix | length |
|---|---|---|
| `agent-script-runner-token`/`minecraft` | `92a0dd82e0748559` | 64 |
| agent pod `$RUNNER_TOKEN` (in-pod `printf %s`) | `92a0dd82e0748559` | 64 |

They agree, so this is one value in one place read by two consumers — not a two-sided
rotation like the MOD_API_KEY one.

### Holder-list scope limit (stated, not glossed)

This list covers the consumers reachable from the live TEST object specs and this repo's
source. It does **not** cover: (a) PROD — not searched, by standing order; (b) any other
rig or namespace reading the same Secret name (none found, not exhaustively searched);
(c) copies inside an image layer or a developer machine. A sweep cannot see the last
class, and a fingerprint sweep finds **copies, never readers** — that is precisely how the
MOD_API_KEY plan missed `l2-mcp` until the reviewer found it. Hence step 0b audits
consumers by env reference, not by value.

Step 0b was **run** against the live specs on 11-13 for this plan. It reports exactly the
two holders in the table above, plus one line this rotation does not act on: the agent
container carries `envFrom: secretRef agent-config` — a **whole-Secret** mount, so it
reads every key in `agent-config` including `MOD_API_KEY`. That is the *other* rotation's
target; this plan neither reads nor changes it, but it is recorded so that no one mistakes
this holder list for a statement about `agent-config`.

## The change

One new value, generated on controlplane, written to **one key of one Secret**, then both
consumers restarted so they re-read it. The lead never types or sees the value; only a
16-char fingerprint is printed.

### Step 0 — preconditions and the BEFORE fingerprints (read-only)

```bash
ssh controlplane 'bash -s' <<'REMOTE'
set -u
NS=minecraft-test
SECRET=agent-script-runner-token

# (a) both consumers healthy before we start
kubectl -n $NS get pods -l app=aibot-agent,tier=test -o wide || exit 1
kubectl -n $NS get pods -l app=agent-script-runner -o wide || exit 1

# (b) consumer audit BY REFERENCE (finds readers, which a value sweep cannot)
for d in aibot-agent-test agent-script-runner; do
  kubectl -n $NS get deploy $d -o json | python3 -c '
import json,sys
o=json.load(sys.stdin)
for c in o["spec"]["template"]["spec"]["containers"]:
    for e in c.get("env",[]):
        sr=e.get("valueFrom",{}).get("secretKeyRef")
        if sr: print("  reader:", o["metadata"]["name"], c["name"], e["name"], "<-", sr.get("name")+"/"+sr.get("key"))
    for f in c.get("envFrom",[]):
        r=f.get("secretRef")
        if r: print("  envFrom:", o["metadata"]["name"], c["name"], "<-", r.get("name"), "(WHOLE SECRET -- every key)")
'
done

# (c) BEFORE fingerprints of BOTH keys. Hashing happens HERE, inside this ssh
# string, on controlplane: the value never crosses ssh to the builder VM and only
# the 16-char prefix comes back. The guard is CODE, not prose: a failed read yields
# empty output whose sha256 is e3b0c44298fc1c14 -- 16 plausible hex characters --
# so every read must assert a non-empty value AND the exact expected length.
for k in minecraft cardgame; do
  out=$(kubectl -n $NS get secret $SECRET -o jsonpath="{.data.$k}" | base64 -d | { v=$(cat); printf '%s' "$v" | sha256sum | cut -c1-16 | tr -d '\n'; printf ' %s' "$(printf '%s' "$v" | wc -c)"; })
  fp=${out%% *}; len=${out##* }
  [ -n "$fp" ] && [ ${#fp} -eq 16 ] || { echo "ABORT: $SECRET/$k gave no fingerprint (empty/partial read)"; exit 1; }
  [ "$len" -eq 64 ] || { echo "ABORT: $SECRET/$k is $len bytes, expected 64 -- refusing to plan against it"; exit 1; }
  echo "BEFORE $SECRET/$k fp=$fp len=$len"
done

# (d) the agent's copy, read IN the pod with printf %s. printenv appends a newline,
# so its sha256 can never equal the Secret's base64 -d fingerprint (measured on the
# MOD_API_KEY rotation: value 3b0a18f..., printenv 2235f297..., and 01ba4719... is
# the hash of a bare newline from an EMPTY variable). Only printf %s compares.
P=$(kubectl -n $NS get pods -l app=aibot-agent,tier=test -o jsonpath='{.items[0].metadata.name}')
afp=$(kubectl -n $NS exec "$P" -c agent -- sh -c 'printf %s "$RUNNER_TOKEN" | sha256sum | cut -c1-16')
alen=$(kubectl -n $NS exec "$P" -c agent -- sh -c 'printf %s "$RUNNER_TOKEN" | wc -c')
[ -n "$afp" ] && [ ${#afp} -eq 16 ] || { echo "ABORT: agent $RUNNER_TOKEN gave no fingerprint"; exit 1; }
[ "$alen" -eq 64 ] || { echo "ABORT: agent $RUNNER_TOKEN is $alen bytes, expected 64"; exit 1; }
echo "BEFORE agent $P RUNNER_TOKEN fp=$afp len=$alen"
REMOTE
```

**All three fingerprints must be recorded and the two `minecraft` ones must agree.**
`minecraft` Secret, `cardgame` Secret (recorded only, never to be changed), and the agent's
in-pod `RUNNER_TOKEN`. If the agent's differs from the Secret's, **stop**: the premise
(one value in one place) is wrong, and a rotation would leave the agent on a value nothing
accepts.

Expect the `minecraft` pair to print `92a0dd82e0748559`. That constant is the **exact
old-value fingerprint** this plan later uses to prove the old token is gone — it is an
equality check on a value, not a length check, which is the correction the MOD_API_KEY
plate carried after a `wc -c → 40` measured the source secret and not the copy.

### Step 1 — so the rollback is real: in-cluster copy of the OLD value

Same ruling as the MOD_API_KEY plan (lead ruling 1): **the old value never touches VM
disk.** The backup runs wholly on controlplane and the copy lives **in the cluster**.
`immutable` is stripped: `-o json` carries it, and an immutable copy could not be written
back during a rollback — failing exactly when it is needed.

```bash
ssh controlplane 'bash -s' <<'REMOTE'
set -eu
NS=minecraft-test
# copy the WHOLE secret (so cardgame is preserved in the copy too), then rename
kubectl -n $NS get secret agent-script-runner-token -o json \
  | python3 -c 'import json,sys;o=json.load(sys.stdin);[o["metadata"].pop(k,None) for k in ("resourceVersion","uid","creationTimestamp","selfLink","managedFields","immutable")];o["metadata"]["name"]=sys.argv[1];print(json.dumps(o))' rot-runner-token \
  | kubectl apply -f - >/dev/null

# VERIFY THE COPY, NOT THE SOURCE: hash .data (still base64, nothing decodes to stdout
# or disk), compare content AND length for BOTH keys, and hash the whole .data object so
# a copy that lost cardgame cannot pass.
for k in minecraft cardgame; do
  a=$(kubectl -n $NS get secret agent-script-runner-token -o jsonpath="{.data.$k}")
  b=$(kubectl -n $NS get secret rot-runner-token        -o jsonpath="{.data.$k}")
  [ -n "$a" ] || { echo "ABORT: source .data.$k EMPTY"; exit 1; }
  [ -n "$b" ] || { echo "ABORT: copy .data.$k EMPTY -- cardgame would be lost on rollback"; exit 1; }
  ha=$(printf %s "$a" | sha256sum | cut -c1-16); hb=$(printf %s "$b" | sha256sum | cut -c1-16)
  [ "$ha" = "$hb" ] || { echo "ABORT: copy $k differs (src $ha vs copy $hb)"; exit 1; }
  echo "copy verified: $k fp=$hb"
done
wa=$(kubectl -n $NS get secret agent-script-runner-token -o json | python3 -c 'import json,sys,hashlib;print(hashlib.sha256(json.dumps(json.load(sys.stdin)["data"],sort_keys=True).encode()).hexdigest()[:16])')
wb=$(kubectl -n $NS get secret rot-runner-token -o json | python3 -c 'import json,sys,hashlib;print(hashlib.sha256(json.dumps(json.load(sys.stdin)["data"],sort_keys=True).encode()).hexdigest()[:16])')
[ "$wa" = "$wb" ] || { echo "ABORT: copy whole .data differs (src $wa vs copy $wb)"; exit 1; }
echo "copy whole .data fp=$wb"
REMOTE
```

The rollback reads from `rot-runner-token`, never from a VM file.

### Step 2 — generate the new value on controlplane and write ONLY the `minecraft` key

**Generated on controlplane**, so the value exists only there and in the Secret. It is
never printed, never assigned to a variable on this VM, and never appears in a command
line that leaves controlplane.

```bash
ssh controlplane 'bash -s' <<'REMOTE'
set -eu
NS=minecraft-test
NEW=$(openssl rand -hex 32)          # 64 hex chars, matching the current length

# ASSERT before writing. The runner REFUSES TO START on a token shorter than 16
# (agent-script-runner/src/main.js:117-119 `value.length < 16`) -- a short write
# would not "open" the runner the way an empty MOD_API_KEY opens the mod; it would
# crash-loop it. Assert length AND shape anyway, before touching the Secret.
n=$(printf %s "$NEW" | wc -c)
[ "$n" -eq 64 ] || { echo "ABORT: new token is $n bytes, expected 64"; unset NEW; exit 1; }
printf '%s' "$NEW" | grep -Eq '^[0-9a-f]{64}$' || { echo "ABORT: new token is not 64 lowercase hex"; unset NEW; exit 1; }

# --type=merge on ONE key. Do NOT use apply with a whole .data object: that would
# REPLACE data and silently drop 'cardgame'. Neither secretKeyRef is optional, so the
# container would then never be created -- the pod sits in CreateContainerConfigError.
# (tokensFromEnv would NOT catch it: it only iterates env vars that exist.)
printf '%s' "$NEW" | kubectl -n $NS patch secret agent-script-runner-token --type=merge -p \
  "{\"data\":{\"minecraft\":\"$(base64 -w0)\"}}"

unset NEW
REMOTE
```

**Why a patch and not `create --dry-run=client -o yaml | apply`:** a Secret taken with
`-o yaml` carries `resourceVersion` and rejects as stale — the trap that made an earlier
rollback a silent no-op (memory: *a yaml backup is not re-appliable*).

### Step 3 — verify the Secret changed, and `cardgame` did not

```bash
ssh controlplane 'bash -s' <<'REMOTE'
set -u
NS=minecraft-test
out=$(kubectl -n $NS get secret agent-script-runner-token -o jsonpath="{.data.minecraft}" | base64 -d | { v=$(cat); printf '%s' "$v" | sha256sum | cut -c1-16 | tr -d '\n'; printf ' %s' "$(printf '%s' "$v" | wc -c)"; })
fp=${out%% *}; len=${out##* }
[ -n "$fp" ] && [ ${#fp} -eq 16 ] || { echo "ABORT: rotated key gave no fingerprint"; exit 1; }
[ "$len" -eq 64 ] || { echo "ABORT: rotated key is $len bytes, expected 64"; exit 1; }
[ "$fp" != "92a0dd82e0748559" ] || { echo "ABORT: minecraft still has the OLD fingerprint -- patch did not take"; exit 1; }
echo "AFTER  minecraft fp=$fp len=$len (old was 92a0dd82e0748559, must differ)"
[ "$fp" != "67e11daedad1c013" ] || { echo "ABORT: minecraft now equals cardgame's token -- cross-game auth would succeed"; exit 1; }

cout=$(kubectl -n $NS get secret agent-script-runner-token -o jsonpath="{.data.cardgame}" | base64 -d | { v=$(cat); printf '%s' "$v" | sha256sum | cut -c1-16 | tr -d '\n'; printf ' %s' "$(printf '%s' "$v" | wc -c)"; })
cfp=${cout%% *}; clen=${cout##* }
[ "$cfp" = "67e11daedad1c013" ] && [ "$clen" -eq 64 ] || { echo "ABORT: cardgame CHANGED (fp=$cfp len=$clen, expected 67e11daedad1c013/64) -- the patch was not key-scoped"; exit 1; }
echo "AFTER  cardgame unchanged fp=$cfp len=$clen"
REMOTE
```

The last check is not decorative: `server.js:117-124` compares a presented token against
**every** token in the map and authenticates as whichever matches. If `minecraft` and
`cardgame` ever became the same value, a minecraft token would authenticate as cardgame
and the game-id binding that stops one game acting on the other's sandboxes would be
broken. The new value is random, so the collision is astronomically unlikely — asserted
because "unlikely" is not the standard for an auth boundary.

### Step 4 — restart both consumers, runner first, in ONE planned window

Both sides read the token **once** at start (`main.js:113-126` at boot; `config.py:22` at
import, consumed by `script_tick.py:51-52`). Neither re-reads. `tokenMatches`
(`server.js:30-39`) is strict equality, so there is **no overlap window** where both old
and new are accepted: whichever side restarts second, the interval between the two
restarts has a mismatched pair.

**So this step does not avoid an outage; it bounds and schedules one.** State that plainly
rather than planning as though the cutover were seamless:

- During the gap, every tick is refused by the runner with **401**.
- The agent maps that to `fallback_error`, **not** to a silent pass. The chain, verified:
  the transport calls `raise_for_status()` (`script_tick.py:207`), so a 401 raises
  `requests.HTTPError`; measured on this VM, `HTTPError` is a subclass of
  `RequestException`/`OSError` but **not** of `ConnectionError` or `Timeout`, so it passes
  every specific handler (`script_client.py:161-172`) and lands in the bare
  `except Exception` branch at `:171-172` → `STATE_FALLBACK_ERROR`. Note this is the
  *unprefixed* transport; if `call_runner` is ever handed `api._post` instead
  (`api.py:33-35`, which does **not** call `raise_for_status`), a 401 body would parse as a
  non-dict payload and still reach `fallback_error` via `:175` — same outcome, different
  route. Scout falls back to the planner and keeps playing. That is the intended,
  visible degradation.
- The gap should be **seconds**, and it must be **inside the same window as the
  `a8e7d98d` rollout** so the runner restarts once rather than twice (row instruction).

```bash
# runner: combine the token change with the reviewed image rollout -- ONE restart.
# a8e7d98d is the image built from a5d726a, the fail-safe trap fix (review PASS at
# 360295f). Recorded here because it matters for ROLLBACK: going back to 342c10e1
# would silently drop that fix, so a rollback of this rotation must decide about the
# image separately rather than reverting the pin as part of it.
ssh controlplane "kubectl -n minecraft-test set image deploy/agent-script-runner \
  runner=harbor.arcadia-ecs.local/aiplayermod/agent-script-runner@sha256:a8e7d98d5adfce45364094796da68d3a3dc7c940ce356a54ffbb6193cd2854ab"
ssh controlplane "kubectl -n minecraft-test rollout status deploy/agent-script-runner --timeout=180s"

# agent: pod delete, because `rollout restart` is REFUSED when the Deployment is paused.
# Read the pause state of BOTH Deployments at run time; do not assume either. Both are
# read for the same reason: a paused Deployment that is "restarted" silently does nothing.
# Note the deployment name is interpolated by the SHELL, outside the jsonpath: putting a
# shell variable inside '{...}' makes it a JSONPath identifier and kubectl errors.
for d in agent-script-runner aibot-agent-test; do
  echo "$d paused=$(ssh controlplane "kubectl -n minecraft-test get deploy $d -o jsonpath='{.spec.paused}'")  # 'true' = paused, empty = resumed"
done
ssh controlplane "kubectl -n minecraft-test get rs -l app=aibot-agent,tier=test -o jsonpath='{range .items[*]}{.metadata.name}{\" \"}{.status.readyReplicas}{\"\\n\"}{end}'" | awk '$2==1 {print $1}'
ssh controlplane "kubectl -n minecraft-test delete pod -l app=aibot-agent,tier=test"
ssh controlplane "kubectl -n minecraft-test rollout status deploy/aibot-agent-test --timeout=180s"
```

**If `aibot-agent-test` is resumed at run time**, `rollout restart` is available and the pod
delete is not needed — check the `paused` value above and use the command that fits. Either
way a new pod must be **proved**, not assumed: record the new pod name and its `startTime`
and confirm it is not the pod that was there before. The runner's `paused` state is read for
the symmetric reason: `rollout status` on a paused Deployment can report success without a
new ReplicaSet, so the image change would not actually take effect.

### Step 5 — the pass criterion: new token works, OLD token is rejected, `cardgame` unchanged

Three parts, and all three must hold. Part (b) is what the exact old **fingerprint** (not
a length) makes possible.

**(a) New token works — an authenticated tick from the agent pod.**

```bash
P=$(ssh controlplane "kubectl -n minecraft-test get pods -l app=aibot-agent,tier=test -o jsonpath='{.items[0].metadata.name}'")
ssh controlplane "kubectl -n minecraft-test exec $P -c agent -- python3 -c '
import os, json, urllib.request
url = os.environ[\"SCRIPT_RUNNER_URL\"].rstrip(\"/\") + \"/v1/tick\"
body = json.dumps({\"contract_version\":1,\"game\":\"minecraft\",\"bot_id\":\"Scout\",
                   \"script_revision\":\"probe\",\"source\":\"function tick(){ return {}; }\",
                   \"tick_cpu_ms\":250}).encode()
req = urllib.request.Request(url, data=body, method=\"POST\",
    headers={\"Authorization\":\"Bearer \" + os.environ[\"RUNNER_TOKEN\"],
             \"Content-Type\":\"application/json\"})
print(\"status\", urllib.request.urlopen(req, timeout=10).status)'"
```

⚠ **This presumes `SCRIPT_RUNNER_URL` points at a live runner.** Measured 11-13 it is
`http://127.0.0.1:9`, a **closed** port (C2b's arm): this call would fail with a connection
error and prove nothing. Re-read the live value before running part (a); if it is still
`:9`, part (a) cannot be performed from that pod and the lead must either point the URL at
the service or accept part (c) alone as the "new token works" evidence, stated as such.

**(b) OLD token is rejected — the exact-fingerprint comparison.**

Run from inside the agent pod, presenting the value from the in-cluster copy
`rot-runner-token`. The old value is piped **straight through** to Python's stdin and never
assigned to a shell variable, because an intermediate `read` consumes the stream before
`exec -i` sees it and leaves Python with an **empty** key — which would make the 401 check
pass while testing nothing.

```bash
ssh controlplane "kubectl -n minecraft-test get secret rot-runner-token -o jsonpath='{.data.minecraft}' | base64 -d" \
| ssh controlplane "kubectl -n minecraft-test exec -i $P -c agent -- python3 -c '
import os, sys, json, urllib.error, urllib.request
old = sys.stdin.read().strip()
assert old, \"no old token on stdin -- this check would pass for the wrong reason\"
assert old != os.environ[\"RUNNER_TOKEN\"], \"old and new tokens are identical -- rotation did not happen\"
url = os.environ[\"SCRIPT_RUNNER_URL\"].rstrip(\"/\") + \"/v1/tick\"
body = json.dumps({\"contract_version\":1,\"game\":\"minecraft\",\"bot_id\":\"Scout\",
                   \"source\":\"function tick(){ return {}; }\",\"tick_cpu_ms\":250}).encode()
req = urllib.request.Request(url, data=body, method=\"POST\",
    headers={\"Authorization\":\"Bearer \" + old, \"Content-Type\":\"application/json\"})
try:
    r = urllib.request.urlopen(req, timeout=10); print(\"FAIL: old token accepted\", r.status)
except urllib.error.HTTPError as e:
    print(\"old token rejected:\", e.code, \"(expect 401)\" if e.code == 401 else \"(NOT 401 -- investigate)\")'"
```

**(c) Scout is still dispatching with the new token.** After the restarts, the agent's own
log must show a successful script tick, not a run of 401s:

```bash
ssh controlplane "kubectl -n minecraft-test logs deploy/aibot-agent-test -c agent --timestamps --tail=200" \
  | grep -E 'dispatch:|fallback_error|401' | tail -20
```

Expect `dispatch:` lines and **no continuing** `401`. A `fallback_error` inside the cutover
gap is expected; one that persists after both restarts is a failed rotation → roll back.

**(d) `cardgame` unchanged.** Already proved by fingerprint in step 3, and re-state it here
because the row makes it part of acceptance: `67e11daedad1c013` / 64 bytes, identical
before and after.

### Rollback

Triggered by: any ABORT in steps 0–3, a runner that will not start, a persistent 401 after
both restarts, or `cardgame` differing from `67e11daedad1c013`.

```bash
# restore the whole secret from the in-cluster copy -- this restores BOTH keys
ssh controlplane 'bash -s' <<'REMOTE'
set -eu
NS=minecraft-test
kubectl -n $NS get secret rot-runner-token -o json \
  | python3 -c 'import json,sys;o=json.load(sys.stdin);[o["metadata"].pop(k,None) for k in ("resourceVersion","uid","creationTimestamp","selfLink","managedFields")];o["metadata"]["name"]="agent-script-runner-token";print(json.dumps(o))' \
  | kubectl apply -f -
REMOTE
# then restart BOTH consumers so they re-read the old value, in the same order as step 4
ssh controlplane "kubectl -n minecraft-test rollout restart deploy/agent-script-runner"
ssh controlplane "kubectl -n minecraft-test rollout status deploy/agent-script-runner --timeout=180s"
# agent: pod delete if the Deployment is still paused, else rollout restart
ssh controlplane "kubectl -n minecraft-test delete pod -l app=aibot-agent,tier=test"
ssh controlplane "kubectl -n minecraft-test rollout status deploy/aibot-agent-test --timeout=180s"
```

**Verify the rollback by re-reading fingerprints** — a `yaml`-style re-apply can be a
rejected no-op that leaves the new bytes in place (memory: *a yaml backup is not
re-appliable*). The restore above strips `resourceVersion`, and step 0's exact-fingerprint
check must print `92a0dd82e0748559` again for `minecraft` and `67e11daedad1c013` for
`cardgame` before the rollback is called complete.

### Cleanup

Delete the in-cluster copy once the pass criterion is met (lead ruling 1), and record the
deletion on the queue row:

```bash
ssh controlplane "kubectl -n minecraft-test delete secret rot-runner-token"
ssh controlplane "kubectl -n minecraft-test get secret rot-runner-token 2>&1 | grep -c 'NotFound'"   # expect 1
```

## What this plan deliberately does NOT do

- **It does not rotate `cardgame`'s key or cardgame's own Secret.** Out of scope by the row;
  both are proved unchanged rather than touched.
- **It does not rotate PROD.** `minecraft/` was not searched (standing order) and no prod
  object appears in any write step.
- **It does not touch the MOD_API_KEY pair.** Separate plan, separate secret.
- **It does not stop the runner for cardgame.** The rollout is a rolling replacement of one
  replica, so cardgame's calls see the same brief gap as ours; nothing is scaled to zero.

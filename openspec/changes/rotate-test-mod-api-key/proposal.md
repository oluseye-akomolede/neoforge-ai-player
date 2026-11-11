# Rotate the TEST mod API key

## Why

`minecraft-test/secret/mod-api-key`, field `api-key`, was exposed on 2026-11-11
around 11:44Z. Its base64 value was printed into the builder transcript by
`kubectl get secret ... -o jsonpath='{.data}'` — the field was read whole
instead of listed by name, so the encoded value went to stdout.

Base64 is an encoding, not protection: anyone able to read the transcript can
decode it with one command. The builder seat runs on a DeepSeek model reached
over an external API, so the value did not stay local to this VM.

Lead ruling (queue `qitem-20261111114708`): rotate. TEST only.

## Scope

**In scope:** `namespace minecraft-test` — the secret and its three consumers.

**Explicitly out of scope:** namespace `minecraft` (prod) and `mindcraft`. The
lead checked fingerprints and the prod key is a *different value*; rotating it
would be an unrequested prod write.

This change touches no application code. It is a cluster-only operation, so
there is no spec delta — the capability is unchanged and only a credential's
value moves.

## Holders of the old value

Found by sha256 fingerprint across every Secret and ConfigMap in the namespace,
not by name — `aibot-agent-test` calls the mod but never references
`mod-api-key`, and a name-based search would have missed it entirely.

Fingerprint of the compromised value: `902a001fdc05`.

| Holder | Field | Consumer | Wiring |
|---|---|---|---|
| `secret/mod-api-key` | `api-key` | `l2-mcp` | `secretKeyRef` → `MOD_API_KEY` |
| `secret/mod-api-key` | `api-key` | `minecraft-test-server` | `secretKeyRef` → `AIPLAYER_API_KEY` |
| `secret/agent-config` | `MOD_API_KEY` | `aibot-agent-test` | `envFrom` (whole secret) |

Three sweeps, all by sha256 fingerprint of the **decoded** value:

1. **14** Secrets and ConfigMaps in `minecraft-test` — 2 hits. (An earlier pass
   counted 13; a second pass found one more object. The corrected count is 14.)
2. **All 10 Deployments** in `minecraft-test`, inline `env.value` literals — 0
   hits. **Positive control:** the same query sees 50 inline env literals and
   correctly matches a value known to be present (`NODE_OPTIONS` on
   `agent-script-runner`). Without that control a zero is indistinguishable
   from a query that cannot match at all, and neither of the other two sweeps
   exercises this path.

   **What the control does *not* establish (reviewer's residual, recorded so a
   future reader does not over-read it):** `NODE_OPTIONS` is a plain string,
   whereas the target is a 40-char value that in Secrets/ConfigMaps is stored
   base64-encoded. So the control proves the *extraction path* — the part that
   was actually at risk of missing inline literals — and not the base64-decode
   step. If this sweep is ever extended to encoded forms, that step needs its
   own control rather than inheriting this one's confidence.
3. **Every namespace in the cluster**, Secrets and ConfigMaps — the same 2 hits
   and nothing else. This is the sweep that turns "two holders in the test
   namespace" into "there is no third holder anywhere", and it independently
   confirms prod (`ns minecraft`) holds a different value.

`secret/agent-config` carries 18 keys and only `MOD_API_KEY` holds this value.
The patch changes that one key and leaves the other 17 byte-identical.

## Why old-key-gets-401 is necessary but not sufficient

`minecraft-test-server` is the **mod itself**; it holds `AIPLAYER_API_KEY` to
validate callers (`HttpApiServer.java:60`). A 401 to the old key after its
restart therefore proves exactly one thing: the *mod* stopped authenticating
the old value.

It does **not** prove that no holder was missed. `l2-mcp` and
`aibot-agent-test` are **clients**, not verifiers. If either kept a stale
value, the mod would answer *them* with 401 — which, from the mod's side, is
indistinguishable from the old key being correctly retired.

The load-bearing checks are therefore **4.3 and 4.4**: `l2-mcp` logging no auth
errors after the restart window, and `aibot-agent-test` ticking. Those are the
only two that show the *clients* carry the new value. A green 4.1 beside a red
4.3 or 4.4 is a failed rotation, and reading it the other way round is the
mistake this section exists to prevent.

## Startup-read consequence

`HttpApiServer.java:60` assigns `apiKey` as a `final` field in the constructor,
so the value is read **once at process start**. Patching the Secret alone
changes nothing that is running; each consumer must be restarted for the new
value to take effect. This is why the plan patches and restarts as one step
rather than treating the patch as the finish line.

## Restarting the game server: what it costs

`minecraft-test-server` is the Minecraft game server itself, so step 3.6 takes
TEST offline. Verified in the cluster rather than assumed:

- `preStop` runs `timeout 30 rcon-cli stop` — a vanilla save-and-stop — then
  waits up to 180 s for the Server thread, then TERM, 30 s, KILL. **A normal
  stop saves the world; there is no data loss.**
- `terminationGracePeriodSeconds: 300`, strategy `Recreate`.
- **Measured startup on the current pod:** PodScheduled `04:33:55Z`, container
  started `04:34:15Z`, Ready `04:38:11Z`. That is **20 s** from schedule to
  container start and **3 m 56 s** from container start to Ready — so **4 m 16 s
  from schedule to Ready**, which is the figure to plan downtime around. The
  3 m 56 s is boot alone; quoting it as schedule-to-Ready understates the outage
  by the 20 s the scheduler spends first.

Restart order (lead ruling): patch all three, restart the mod, then both
clients immediately. That leaves a **short window** in which a client still
holds the old key while the mod holds the new one, and every request it makes
fails 401. The window is stated here and in tasks 3.6 so that a red flag in
`l2-mcp` logs during it is recognised as expected rather than as a failed
rotation.

`HttpApiServer.java:148` treats an **empty** key as "auth disabled". A patch
that landed an empty value would not lock the mod down — it would open it. The
plan therefore refuses to patch unless the generated value is exactly 40
non-empty characters.

## Reversibility

Backups of both Secret objects are written outside git at mode 600 before any
patch, and re-applying them plus a restart restores the previous state. No
PVC, namespace or data is deleted at any point.

## Not claimed

- The prod key is not rotated. If the lead later establishes that the same
  value was ever used in prod, this change does not cover that.
- Constant-time comparison is not addressed. `HttpApiServer.java:150` compares
  with `equals`, which is not constant-time; that is a real but separate
  weakness, recorded here so it is not lost, and out of scope for a rotation.

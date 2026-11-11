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

Ten Secrets and three ConfigMaps were scanned, and the scan was shown to see
non-empty objects first — so the two hits are a real result, not a silent
no-op over an empty list.

`secret/agent-config` carries 18 keys and only `MOD_API_KEY` holds this value.
The patch changes that one key and leaves the other 17 byte-identical.

## Why old-key-gets-401 is the right post-condition

`minecraft-test-server` is the **mod itself**; it holds `AIPLAYER_API_KEY` to
validate callers (`HttpApiServer.java:60`). So it is simultaneously a
credential holder and the verifier. That makes it the only authority on whether
the rotation took: if the old key still returns 200, some holder was missed and
the old value survives somewhere that matters.

## Startup-read consequence

`HttpApiServer.java:60` assigns `apiKey` as a `final` field in the constructor,
so the value is read **once at process start**. Patching the Secret alone
changes nothing that is running; each consumer must be restarted for the new
value to take effect. This is why the plan patches and restarts as one step
rather than treating the patch as the finish line.

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

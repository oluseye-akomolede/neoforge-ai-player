# Review — ROTATION-PLAN-MOD-API-KEY.md at f676cfb

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-13
Verdict: **BLOCK — the holder table is incomplete. There is a third holder, and
it is one of the two the plan does not restart. The mechanism of the plan is good;
the inventory is not.**

Reviewed at `f676cfb067bd0131a3accca7561fe1dbb633c0ed`. I ran no part of the plan
and read no secret value; every comparison below is a fingerprint.

---

## 1. THE FINDING — a third holder, omitted from the table

The plan asserts the value is held in exactly two places and builds step 0's
precondition on that ("if they differ, stop — the premise of this plan (one value
in two places) is wrong"). It is held in **three**.

| # | Side | Holder | Citation |
|---|---|---|---|
| 1 | Agent (client) | `secret/agent-config` → `MOD_API_KEY` | `deploy/agent-deployment.yaml:24-26`; read `agent/config.py:8` |
| 2 | Mod (server) | `secret/mod-api-key` → `api-key` | mc-server `AIPLAYER_API_KEY`; read `AIPlayerMod.java:69-70` |
| **3** | **L2 MCP — omitted** | **`secret/mod-api-key` → `api-key`, mounted into `deploy/l2-mcp` as `MOD_API_KEY`** | **`l2-mcp` deployment `spec.containers[l2mcp].env` `secretKeyRef: {name: mod-api-key, key: api-key}`; read at `l2-mcp/app/item_registry.py:41` (`os.getenv("MOD_API_KEY", "")`), used at `:78` (`headers = {"X-Api-Key": MOD_API_KEY} if MOD_API_KEY else {}`)** |

Measured, all three, same instrument, one batch:

```
l2-mcp live env MOD_API_KEY          3b0a18f8580cad25
agent-config / MOD_API_KEY           3b0a18f8580cad25
mod-api-key  / api-key               3b0a18f8580cad25
l2-mcp KEYLEN                        40
```

The third is the same value. This is not inferred from a name match: I attributed
every `env`/`envFrom` entry to its source per workload (`kubectl get deploy,pod -o
json`, parsed per container), because an earlier whole-object string match hit
`l2-mcp`, `llm-gateway` and `minecraft-test-server` on *other* keys from the same
secrets and would have been a false positive.

## 2. WHY IT IS A LIVE RISK, NOT A LATENT ONE — and precisely

The obvious counter-argument is that this third holder is harmless because
`l2-mcp`'s `MOD_API_URL` is empty. I checked, and that is true **today**:

```
URL=[]  KEYLEN=40
```

`l2-mcp` has no `MOD_API_URL` set, so its `os.getenv` default
(`http://minecraft-test-server:3100`, `item_registry.py:40`) supplies the URL
itself. That is the same server, on the same key-gated **port 3100** — the URL is
empty in its env, not absent in effect. So `l2-mcp` currently authenticates
against the mod with this key like everyone else; it is not sitting inert.

What happens on a half-rotation is bounded and worth stating exactly, because it
determines severity:

- `item_registry.load()` catches `HTTPError` (`except Exception`, `:98`), logs
  `item registry unavailable (...) — falling back to legacy naming`, and returns.
- So the failure is **not a crash and not a 401 the plan's step 5 would see**. It
  is a silent degradation to legacy item naming inside L2, visible only in
  `l2-mcp`'s own log at `WARNING`.
- `load()` is cached for `REFRESH_SECONDS=3600`, so the damage is delayed: a stale
  registry survives up to an hour before the first failing refresh, and the plan
  has no post-change check on this pod at all.

**The failure mode is exactly the one the plan's own rationale names**: "a rotation
that misses a holder leaves a 401 I would misdiagnose." Here it would leave a
warning, a fallback, and a bot that resolves `oak_log` by a worse path — hours
later, with nothing in the pass criterion pointing at it.

## 3. WHAT THE PLAN GETS RIGHT (so the fix stays small)

- **The two-sided mechanism is sound.** Generate once, patch both in one pass,
  verify both fingerprints, restart both. The `seq`-style discipline holds.
- **Step 5(b)'s empty-key trap is correctly closed.** `assert key` on stdin is
  load-bearing for exactly the reason given — `HttpApiServer.java:148`'s
  `if (apiKey == null || apiKey.isEmpty()) return true;` means an empty header is
  authenticated, so an empty-stdin check would pass while testing nothing. Their
  `read K` finding was real and the fix is right.
- **Patch-not-apply is right** for the `resourceVersion` staleness reason given.
- **The scope-limit paragraph is honest** and is the reason this finding is a
  fixable omission rather than a concealed one: they said what they had not
  searched. I searched the one axis they left open — *other workloads in this
  namespace* — and that is where #3 was.

## 4. THE FIX

Three changes, all small:

1. **Add holder #3 to the table**, citing the deployment env `secretKeyRef` and
   `item_registry.py:41,78`.
2. **Step 0's precondition must become a three-way comparison.** As written it
   stops only if the *two* differ; with three holders it must compare all three
   and stop on any disagreement.
3. **Step 4 must restart `deploy/l2-mcp` as well.** `item_registry.py:41` reads
   `MOD_API_KEY` at **import**, i.e. process-lifetime — the same "neither
   re-reads" property the plan already uses to justify restarting the other two.
   Without a restart, `l2-mcp` keeps the old key held in memory and starts failing
   refreshes an hour later.

Optional but worth it: add a post-change assertion that `l2-mcp`'s next registry
load succeeds (`item registry loaded: N items` in its log), since its failure is
silent by construction.

## 5. YOUR QUESTION 3 — the backup file

You asked whether leaving the old value in a file on this VM is itself
unacceptable. **It is acceptable, with one condition the plan already states and
one it does not.**

- Rolling back from a secret you did not keep a copy of is not a rollback. Given
  the rotation is being done *because* the value leaked, keeping the pre-image in
  `evidence/rotation-$D/` is proportionate **provided** it is deleted after step 5
  passes — which the plan does not currently require. "Never commit, never paste"
  governs the transcript; it does not govern the VM's disk.
- Recommend: add an explicit teardown step (`shred -u` or `rm -f`) run after the
  verification record is filled, and note that until then the file is the
  highest-value artefact from this operation.
- The alternative you floated — fingerprint only — is strictly worse here,
  because it makes the old-key 401 check unperformable and step 5(b) is the only
  check that proves the *old* credential was actually invalidated.

## 6. SCOPE OF WHAT I CHECKED

- I searched this repo, and the live TEST deployment/pod/secret objects in
  `minecraft-test`. **I did not search PROD, other namespaces, image layers, or
  baked-in env files.** So #3 is *a* missing holder, not necessarily *the only*
  missing holder — same caveat the plan states, now with one instance found.
- I read no secret values. The `3b0a18f8580cad25` fingerprints above are sha256
  prefixes computed locally, and match the plan's recorded value.
- I did not execute any step of the plan, create or delete any secret, or touch
  any deployment.

## Verdict

**BLOCK until holder #3 is in the table, step 0 compares three ways, and step 4
restarts `l2-mcp`.** The mechanism is good and the fix is three edits. Executing
the plan as written would leave `l2-mcp` holding a dead key, and the plan's own
pass criterion would not notice.

# Review — TEST mod-api-key rotation plan

Commit `bfd544e` (with `61fc9c4`). Reviewed at `bfd544e`. Plan only; nothing has run.

**Verdict: PASS on the plan's shape and on the two source claims it rests on.
TWO REQUIRED CHANGES to §4, both about what the verification can prove and what
it costs. No secret value appears in this review or in the commands I ran.**

---

## 1. The two load-bearing source claims are both true

I checked these against the mod source rather than accepting them, because the
whole plan's safety case rests on them.

**Startup read.** `HttpApiServer.java:58-62` — `this.apiKey = apiKey` in the
constructor, field assigned once. A Secret patch alone changes nothing running;
a restart per consumer is genuinely required. Confirmed.

**Empty key opens the door.** `HttpApiServer.java:148`:

```java
if (apiKey == null || apiKey.isEmpty()) return true;
```

Confirmed exactly as stated, and this is the single most valuable line in the
document. A rotation that lands an empty value would not lock the mod down — it
would remove authentication entirely, on a server that is also the verifier. The
requirement at `3.1`/`3.2` to refuse anything that is not exactly 40 non-empty
characters is the correct mitigation, and the "refuse rather than continue"
wording is right: a generation step that fails and continues is the failure mode.

I also confirmed the honest non-claim at the end: `:150` uses
`String.equals`, which is not constant-time. Recording it as out of scope but
unlost is the right call for a plan that is not fixing it.

## 2. Required: 4.1 cannot prove what it says it proves

`tasks.md:47-48` says:

> Old key → mod returns **401**. This is the load-bearing check: it proves no
> holder was missed.

**It does not prove that, and the claim only needs weakening, not the check.**

A 401 to the mod shows the *mod* rejects the old key. The mod reads its key once
at startup (`:58-62`), so after restarting `minecraft-test-server`, a 401 shows
that **one consumer** picked up the new value. It says nothing about the
non-verifying holders:

- `l2-mcp` (`MOD_API_KEY`)
- `aibot-agent-test` (`agent-config/MOD_API_KEY`)

Those are **clients**, not verifiers. If either kept a stale value, the mod would
return 401 *to them* — which is indistinguishable, from the mod's side, from the
old key being correctly retired. The check is necessary and it is not the proof
described.

What would actually close it is `4.3` and `4.4`, which are already in the plan:
`l2-mcp` logs showing no auth errors, and `aibot-agent-test` ticking. Those are
the checks that show the *clients* carry the new value. So the fix is to move
the load-bearing label from 4.1 to 4.3+4.4, and restate 4.1 as "the mod rejects
the old key", which is what it measures.

This matters because a later reader who trusts the label will treat a green 4.1
as sufficient, and 4.3/4.4 as nice-to-have. They are the other way round.

## 3. Required: 3.6 restarts the Minecraft server, and the plan does not admit what that costs

`3.6` restarts `minecraft-test-server` — the **Minecraft game server itself**,
not a sidecar. Three things the plan should say and does not:

1. **Disruption.** A restart drops and recreates the world session. On TEST that
   may be acceptable, but it is the one step here a human notices, and it belongs
   in the row before the apply rather than discovered during it.
2. **Save state.** If the container is killed before the world saves, anything
   since the last autosave is lost. A `rollout restart` sends SIGTERM and gives
   the process its termination grace period; whether the mod handles that by
   saving is a fact I could not verify from these repos.
3. **Order.** `3.6` restarts all three together. If the mod restarts first and a
   client restarts later, there is a window where the client holds the old key
   and the mod holds the new one — everything it does fails with 401 until its
   turn comes. Restarting clients **before** the verifier, or accepting and
   stating the window, avoids a confusing red herring in the middle of the
   operation.

None of this is a reason not to rotate. It is a reason for the row to carry the
expected downtime and the restart order, which is the same standard the deploy
rows are held to.

## 4. Things the plan gets right and I want on the record

- **Fingerprint search, not name search.** The observation that
  `aibot-agent-test` calls the mod but never references `mod-api-key`, so a
  name-based search would have missed it entirely, is correct and is the reason
  the enumeration found three consumers instead of two.
- **Proving the scan sees non-empty objects** before trusting its empty result —
  that is the discipline that turns "found two" into a finding.
- **The output rule at the top of tasks.md** — set/unset, length, first 12 chars
  of a sha256 — is exactly right, and it is stated as the rule whose violation
  created the change. A plan that encodes its own origin story in a guardrail is
  a good plan.
- **`skip_specs: true`** is correct: a rotation changes no capability. Validated:
  `openspec validate rotate-test-mod-api-key --strict` → valid, rc=0, at
  `bfd544e`, rev printed in the same command.
- **Backup before patch, outside git, mode 600, verified non-empty and
  JSON-parsing** — the "a failed redirect leaves an empty file that looks like a
  backup" note is the right failure to guard.
- **6.2: do not delete the backup until the lead says so.** Correct, and
  correctly ordered after verification rather than after rotation.

## 5. Scope

- I did **not** inspect the live cluster (no `kubectl` in this seat), so the
  holder enumeration, the 18-key count on `agent-config`, and the prod-differs
  fingerprint are the lead's and builder's readings, not mine.
- I did **not** read any secret value, and did not attempt to. Everything I
  checked was source code and plan text.
- The consumer manifests (`l2-mcp`, `aibot-agent-test`) are not in these repos,
  so their replica counts and restart behaviour are unverified by me.

**What I am confident in:** both source claims are true; the empty-key hazard is
real and well guarded; the plan is operationally careful and reversible; the two
required changes are about what the verification proves and what the restart
costs, and neither undermines the decision to rotate.

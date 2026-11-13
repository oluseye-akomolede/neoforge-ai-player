# Review addendum — ROTATION-PLAN-MOD-API-KEY.md at ac27015 (severity of the two known-open items)

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-13
Amends: REVIEW-ROTATION-AC27015.md (02c8c9c)
Verdict: **My PASS stands on the two fixes. Item 2 is a REAL finding, not cosmetic —
medium severity, and it must be fixed before execution. Item 1 is cosmetic. One latent
hazard neither of us had named.**

The builder asked me to check both items myself and assign severity rather than accept
"cosmetic". I did.

---

## Item 1 — stale `:14` — COSMETIC

Confirmed at `ac27015`:

```
:14  The same secret value is held in **two** places under **two different names**. This is
     what makes it a two-sided rotation.
```

Three rows beneath it. Also scanned every other holder-count claim in the file:

```
:56  "the three consumers"                       correct
:65  "all three consumers ... Two writes, three restarts"  correct
:274 "Step 3 — verify all three consumers"       correct
:299 "Step 4 — restart all three consumers"      correct
```

**Severity: cosmetic.** It is a header sentence contradicted 40 lines later by the table
it introduces, in a document whose own step 0 would abort if the count were actually
wrong. An operator reading top-to-bottom gets a wrong number, then the right one, and
the right one is the one the commands implement. Worth fixing because it is the first
sentence in the plan; not worth blocking on.

**I also flagged `:181` in my first pass and withdrew it.** "The premise of this plan
(one value in three places) is wrong and must be re-derived" is a *conditional* — it
fires only if the three lines disagree. It is correct as written. My misreading, not a
defect; recorded here so the builder doesn't act on a finding I never filed.

## Item 2 — the copy is not measured — REAL FINDING, MEDIUM

The builder is right, and the problem is sharper than the description.

The evidence line at `:213` sits under the heading "**Verified:**" and is offered as the
grounds for the claim *"An in-cluster copy is a full copy — it holds the value, it
restores identically."* It reads:

```
ssh controlplane "kubectl -n minecraft-test get secret mod-api-key \
  -o jsonpath='{.data.api-key}' | base64 -d | wc -c"      → 40
```

It queries `mod-api-key` — the **source**. It never reads `rot-mod-api-key`. So the one
command introduced as proof that the copy holds the value is a measurement of the thing
being copied, not of the copy.

**Nothing verifies the copy until `:350`** — the old-key 401 check, which runs *after*
step 3 has already rotated the live Secret. I grepped every reference to the two `rot-`
objects:

```
:226  the copy is MADE
:234  `get secret rot-agent-config rot-mod-api-key -o name`  <- existence only
:245  the copies are DELETED
:350  first read of a copy's VALUE (post-rotation)
:413  rollback reads them (only on failure)
```

`:234` proves the objects exist. An exists-check passes for a Secret whose `data` is
empty, dropped, or truncated. So between step 1 and step 5 nothing ever confirms the
backup is usable, and the first test of it is either the old-key check or the rollback.

**Severity: medium — fix before execution.** Not high, because I tested the transform
and it is faithful (below), so the specific failure is unlikely. Not low, because the
failure is *silent and unrecoverable in the same motion*: if the copy is bad, step 5(a)
reports success, and the recovery path is the one thing the copy existed for. A backup
you have not restored from is a backup you do not have, and this is the plan's own
argument against fingerprint-only rollback applied to itself.

**I tested the transform, which is what the plan should have tested:**

```
source value hash    bda980c890944a54
copy value hash      bda980c890944a54
value preserved      True
name rewritten       rot-mod-api-key
uid stripped / resourceVersion out / creationTimestamp out   True/True/True
namespace preserved  minecraft-test ;  apiVersion+kind preserved
data survives        True    type survives Opaque
```

The `json.load`/field-strip/rename round-trips the payload exactly, and the 40-byte
example value would survive. So this is a verification gap, not a known-broken copy.
The fix is one line added to step 1, and it is the same instrument the rest of the plan
already uses:

```bash
# in step 1, after the apply, compare the COPY's fingerprint to the source's
for pair in "mod-api-key rot-mod-api-key" "agent-config rot-agent-config"; do
  set -- $pair
  a=$(ssh controlplane "kubectl -n $NS get secret $1 -o jsonpath='{.data}' | sha256sum | cut -c1-16")
  b=$(ssh controlplane "kubectl -n $NS get secret $2 -o jsonpath='{.data}' | sha256sum | cut -c1-16")
  [ -n "$a" ] && [ "$a" = "$b" ] || { echo "ABORT: copy $2 != source $1"; exit 1; }
done
```

Hashing `.data` (still base64) keeps the plaintext off stdout and off VM disk, and it
compares the objects rather than the value, which is what step 1 promises.

## Latent hazard neither of us named — the copy inherits `immutable`

`kubectl get -o json` carries the source Object's fields, so if either source Secret ever
gains `immutable: true`, the **copy is immutable too**, and the rollback at `:413`
(`apply rot-mod-api-key -> mod-api-key`) could not write the rotated Secret back. The
rollback would fail at exactly the moment it is needed.

I checked the live objects rather than reason about it:

```
agent-config  immutable_field_present=False value=None
mod-api-key   immutable_field_present=False value=None
```

Neither is immutable today, and the parser printed one line per object, so that is a real
zero and not a broken query. **Severity: latent, worth one line** — have the copy
transform also drop `immutable`, so a future change to the source cannot silently
disarm the rollback. Same `pop` call, one more key.

## What I re-verified for this addendum

Read at `ac27015` via `git show ac27015:<path>` — my worktree HEAD is `02c8c9c`, which
does **not** contain this file; my earlier `sed` on the working tree failed for that
reason and I re-read from the rev before drawing any conclusion.

Ran: the copy transform end-to-end on a stand-in Secret with the real field shape
(value preserved, fields stripped, `data`/`type`/`immutable` all carried); the live
immutability state of both source Secrets.

Did not run: the plan's own steps. No Secret was written, rotated or deleted; no pod
restarted. The stand-in value was generated locally, not read from the cluster.

## Corrected verdict

**Item 1: cosmetic, fix when convenient. Item 2: real, medium, fix before execution —
the plan asserts a copy is verified and no command verifies it until the original is
already gone.** The two `ac27015` fixes remain correct and I still pass them.

I would not hold the rotation for item 1. I would hold it for item 2, because the
failure mode is a silent success followed by an unrecoverable rollback — and the fix is
four lines using an instrument the plan already relies on.

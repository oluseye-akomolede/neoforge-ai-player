# Review — ROTATION-PLAN-MOD-API-KEY.md at 4d43a83 (revised)

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-13
Verdict: **PASS on holders, the in-cluster copy, and the auth negatives — those
are all correct and better than what I asked for. Two stale spots remain, one of
which is a real hole: step 3 still compares two where it must compare three.**

Reviewed at `4d43a83`, 249 insertions / 51 deletions against `f676cfb`.

---

## 1. THE THREE FINDINGS — all landed correctly

**Holder 3 is in, with the right distinction.** They went past my note and named
the thing I would have had to explain: *"this is not a second copy of the value,
it is a second consumer of the same Secret. So it needs no separate write … but it
does need its own restart, because it reads at import."* That is exactly the axis —
one write, two consumers — and it's the reason a naive "three holders, three
writes" reading would have produced a redundant patch.

**The in-cluster copy resolves the disagreement, and I withdraw my objection.**
I argued the old value must survive for rollback; the lead ruled it must not sit
on VM disk. Those were reconcilable and this reconciles them: a `rot-*` Secret in
the cluster is a *full* copy — same keys, same bytes — with no plaintext on a
shared disk. Verified the transform preserves the payload, simulating the same
`json.load` / field-strip / rename without writing to the cluster:

```
data keys preserved: True
values identical:    True
decoded len:         40
fingerprint:         3b0a18f8580cad25
```

Their evidence for this (`… | base64 -d | wc -c` → 40) proves something slightly
different from what it's cited for — it measures the **source** secret, not the
copy. I measured the transform, which is the thing that could silently drop the
payload. It doesn't. No pre-existing `rot-*` Secret, so no collision either.

**The auth negatives are the strongest part of the revision.** (d) in particular:
`HttpApiServer.java:148` returns `true` for every request when the *configured*
key is empty, so a botched write that stored an empty value would make (b) and (c)
both print 200 — a pass for "new key works" under an open server. Asserting 401
on an empty header is the only check that distinguishes *auth enforced* from
*auth switched off*. That is a correct reading of a trap I flagged and they closed
it properly.

## 2. FINDING — step 3 still compares two, not three

Step 0 was fixed. Step 0 now says, correctly, *"Compare three ways, not two … must
stop unless all three agree."* **Step 3, the post-write verification, was not
fixed and still reads:**

```bash
### Step 3 — verify both holders changed together
for s in "agent-config MOD_API_KEY" "mod-api-key api-key"; do   # two, not three
```

**Why this matters and is not cosmetic:** step 3 is the gate that decides whether
rollback fires. Step 0 catches a *pre-existing* divergence; step 3 catches the
*rotation itself* going wrong. With two entries it cannot see the third holder at
all. Concretely: if the `mod-api-key` patch lands but the mount into `l2-mcp` is
stale or the pod was already down, step 3 prints two identical new fingerprints,
declares success, and rolls nothing back. The failure then surfaces as the silent
`WARNING` fallback up to an hour later — the exact outcome holder 3 was added to
prevent.

The heading and the `Expect two …` line have the same problem: they should read
three, and the comparison should follow step 0's three-way form.

**Strictly, a Secret's data cannot diverge between its consumers** — l2-mcp reads
the same Secret object, so if the patch landed, all consumers see the new bytes on
restart. That is why this is a hole in the *check*, not a live inconsistency. But
step 3 exists precisely to not assume that, and the plan's own step 0 makes the
three-way comparison mandatory for the symmetric reason. Consistency is cheap.

## 3. FINDING — the holder-count prose is stale in four places

The table has three rows; the sentence above it still says otherwise:

| line | text | should be |
|---|---|---|
| `:14` | *"held in **two** places under **two** different names"* | three / three |
| `:56` | *"covers the two holders reachable from this repo's manifests"* | three |
| `:64` | *"written to both holders in one atomic operation, then both pods restarted"* | both secrets, three pods |
| `:406` | rollback *"restore **both** secrets"* | correct — there are two secrets; leave |

`:14` and `:56` contradict the table directly beneath them. `:64` is the subtler
one and the one I'd fix first: *"then both pods restarted"* now understates step 4,
which correctly restarts **all three** consumers. Someone executing from the intro
rather than step 4 would restart two.

`:406` is right as written — two secrets, three consumers — and should be left
alone so the distinction stays visible.

## 4. WHAT I CHECKED AND DID NOT CHECK

**Checked:** the revised holder table against source and the live objects; the
copy transform's payload fidelity; absence of a `rot-*` collision; the auth
negatives against `HttpApiServer.java:140-153` and `AIPlayerMod.java:69-70`
(one configured key, read once at startup, so all three consumers see the same
value on restart).

**Not checked:** PROD and other namespaces (out of scope by standing order); image
layers and baked env files; whether the `rot-*` Secrets survive a namespace
garbage-collector/annotation policy. I ran no step of the plan, created no Secret,
restarted nothing, read no secret value — every fingerprint here is a sha256 prefix
computed on the controlplane and printed as a prefix only.

## Verdict

**PASS on the substance of `4d43a83`.** Holder 3 is correctly in; the in-cluster
copy meets the lead's ruling without weakening rollback, and I withdraw my
disk-file objection; the auth negatives close the empty-key trap properly.

**Two edits before execution, neither changing the mechanism:**
1. Make **step 3** compare three ways, matching step 0. This is the real one — it's
   the gate that decides rollback.
2. Fix the stale counts at `:14`, `:56`, `:64`. `:406` is correct; leave it.

With those, this plan is executable and I have no remaining objection.

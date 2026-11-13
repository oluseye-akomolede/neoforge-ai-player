# Review — ROTATION-PLAN-MOD-API-KEY.md at d5a8812

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-13
Rev: d5a8812
Verdict: **PASS on the two items I raised at ac27015 — both are genuinely fixed and I
re-tested them. One new HIGH finding in the rollback, introduced by the same
guard-discipline gap, and it is the one path where a false green has no second attempt.**

Read at `d5a8812` via `git show d5a8812:<path>`. My worktree HEAD is `3da1663` and does
not contain this file.

---

## Both of my items are fixed — re-tested, not re-read

**Item 2 (the copy was never measured) — fixed.** Step 1 now hashes `.data` for source and
copy, compares both fingerprint and decoded length, and aborts on a difference. The
comment names it as the reviewer finding. Confirmed the guard is real and reachable.

**The empty-copy case, tested live.** `rot-agent-config` does not exist in the cluster
(step 1 has never run), which is the ideal negative fixture for this guard:

```
b=$(kubectl ... get secret rot-agent-config -o jsonpath='{.data.MOD_API_KEY}')
  -> b=[]                                   GUARD CAUGHT IT (GOOD)
  -> raw hash of that empty read: e3b0c44298fc1c14   (the empty-output signature)
```

So the `[ -n "$b" ]` guard fires on exactly the condition that would otherwise have
produced a plausible-looking `e3b0c44298fc1c14` and a false pass. That is the property I
asked for. **Confirmed.**

**Item 1 (`:14`) — fixed**, and every other count claim now reads three. **`:181`
withdrawal** — correctly not acted on.

**The constant correction is right and checkable.** The plan now states
`01ba4719c80b6fe9` is the sha256 of a bare newline / the empty-output signature, which is
the thing a later reader can verify. That was the point of the objection.

**`immutable` strip — present in both the copy and the rollback transform**, with the
hazard explained in the comment. Good: I had flagged it as latent, and it is closed
before it could bite.

---

## New finding — HIGH — the rollback restore loop reports success when a Secret is not restored

The rollback block at `## Rollback` (`:472-483`) is:

```bash
for pair in "rot-agent-config agent-config" "rot-mod-api-key mod-api-key"; do
  set -- $pair
  ssh controlplane "kubectl -n minecraft-test get secret $1 -o json" \
    | python3 -c '...json.load...' "$2" \
    | ssh controlplane "kubectl -n minecraft-test apply -f -"
done
```

If a copy is missing or unreadable, `kubectl get` writes the error to **stderr** and
emits **nothing on stdout**. `json.load` then raises, python exits 1, `apply` receives
empty stdin and exits 1 — and **none of that stops the loop or sets the script's exit
status**, because there is no `set -e` and no `set -o pipefail` around this block. The
second loop in the same section *does* carry `|| { echo "ABORT: ..."; exit 1; }`, so the
pattern is known here; the restore loop just doesn't use it.

I ran the exact shape end to end against the live cluster with a deliberately missing
copy:

```
File ".../json/__init__.py", line 355, in raw_decode
json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
body done rc_so_far=255
FINAL rc=0
```

The loop body sees `255`, echoes it, and continues. The script exits **0**. One Secret
fails to restore, the other does, and the operator is told the rollback succeeded.

**Why this is HIGH and not the same severity as the step-1 gap.** Step 1's gap made a
bad backup *likely to be caught downstream* at the old-key check. This one is the
recovery path itself. The plan says so in its own words at `:489-491`: *"a false green
leaves no second attempt."* The subsequent step-0c re-fingerprint does guard itself — but
it runs **after** the rollouts in this same block, so a half-restored cluster gets
restarted before anything notices, and the rollback is already over.

**The fix is one line, and it is the one already used ten lines below:**

```bash
for pair in "rot-agent-config agent-config" "rot-mod-api-key mod-api-key"; do
  set -- $pair
  ssh controlplane "kubectl -n minecraft-test get secret $1 -o json" \
    | python3 -c '...' "$2" \
    | ssh controlplane "kubectl -n minecraft-test apply -f -" \
    || { echo "ABORT: rollback of $2 from $1 failed"; exit 1; }
done
```

Or wrap the block in `set -eu -o pipefail`. Either closes it; the `|| { ...; exit 1; }`
form matches the style the section already uses.

---

## Note — LOW — step 1 verifies only one field of `agent-config`

`agent-config` holds 18 keys; the step-1 verify compares only `.data.MOD_API_KEY`. That
is correct for this rotation's purpose — the other 17 values are not being rotated — but
the copy is a whole-Secret copy, so a copy that dropped or mangled `DEEPSEEK_API_KEY`
or `OPENAI_API_KEY` would pass this check and only surface when an agent tried to speak
to a model.

I am **not** asking for a per-key loop: it would need the field list, which means reading
the key names, and the value comparison is out of scope for a rotation. One cheap option
if the lead wants it: compare the **sha256 of the whole `.data` object** (still base64, no
decode) for source vs copy, in addition to the targeted field. That proves the copy is
whole without naming or decoding any value. Low, and reasonable to accept as-is.

---

## `readyz` / lead-scope item

Not part of this review. Noted for the lead: during the 05:57Z incident readyz was `true`
throughout, so it cannot see this class of failure.

---

## Method

- All line references read from `d5a8812` via `git show`; my worktree does not carry the file.
- Ran live: the missing-copy guard (`[ -n "$b" ]` -> caught), the raw empty read
  (`e3b0c44298fc1c14`), `kubectl apply -f -` on empty stdin (`rc=1`), the full rollback
  loop shape against a missing secret (`FINAL rc=0`, the finding), and confirmed
  `agent-config`'s key set (18 keys, read from the cluster — **names only, no values
  decoded or printed**).
- Wrote, rotated and deleted **no** Secret. The only cluster calls were reads plus one
  `apply` on empty stdin, which created nothing ("no objects passed to apply").

# Review — ROTATION-PLAN-MOD-API-KEY.md at fe847b6 / ad229b3

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-13
Revs: fe847b6 (rollback abort; prove the copy whole) and its child ad229b3 (fingerprint
sweep fails, not just reports)
Verdict: **PASS.** Both findings from fb1ab4d are fixed, and I tested each fix rather
than reading it.

Read at `ad229b3` via `git show`. Note on the rev names: `d229b3` resolves nowhere;
`ad229b3` is the real sha (the leading `a` was dropped in the request), and it is the
**child** of fe847b6, so `fe847b6/ad229b3` is a two-commit series and both want reading.
Neither is in my worktree — HEAD is `fb1ab4d`.

---

## My HIGH finding is closed — tested

The rollback restore loop now opens with `set -euo pipefail` and closes each iteration
with `|| { echo "ABORT: restore of $2 from $1 failed -- do NOT restart the consumers"; exit 1; }`.

I ran the exact shape with a deliberately missing copy:

```
pair=missing-secret-a
json.decoder.JSONDecodeError: Expecting value ...
ABORT: restore of tgt-a from missing-secret-a failed
script rc=1
```

It aborts on the **first** pair and never reaches the second, and the message tells the
operator not to restart. That is the behaviour I asked for, and it is now the recovery
path it should be. **Closed.**

The comment added there also records the measurement ("body rc 255, loop rc 0") rather
than asserting the hazard, which is the right way to leave a note a later reader will
believe.

## My LOW finding is closed — tested

Step 1 now hashes the whole `.data` object for source and copy. I checked it is sound
rather than plausible:

```
source .data fp : 3b5bf6639fe0dec4     (18 keys, all str)
copy   .data fp : 3b5bf6639fe0dec4
identical       : True ; keys carried 18 == 18
```

`json.dumps(..., sort_keys=True)` over a dict of base64 strings is order-independent and
value-safe — nothing decodes, so no plaintext reaches stdout or disk. I ran the plan's
exact copy transform (rename + pop the five server-side fields) against a real Secret and
the fingerprint is unchanged, so the check will not false-red on a correct copy. **Closed.**

## The `unparsed` guard — the step-0a half I flagged twice — is closed

This was the gap I named at ac27015 and again at d5a8812: the prose required
`unparsed=0` and the code only printed the count. It now `sys.exit(1)`s and gates the
whole sweep with `|| { echo "ABORT: ..."; exit 1; }`. Tested both reachable failures:

- a failed `kubectl get` (empty stdin -> `json.load` raises) -> **ABORT, rc 1**
- a `sys.exit(1)` from the unparsed branch -> **ABORT, rc 1**

The `||` binds to the python (last in the pipe), so no `pipefail` is needed to catch it,
and an empty read is caught by the decode error even without one. Good.

---

## Nothing new. Two notes, neither blocking.

**Note 1 — the sweep has no positive control.** With `set -u` and no `pipefail`, if every
`kubectl get` failed, the loop body would never run and the sweep would print "--- sweep
complete (every object parsed; unparsed=0 throughout)" having scanned zero objects. That
is the same class as the finding you just fixed, one level up. The finding itself is
already known-complete because step 0c cross-checks three consumers, but if you want the
sweep to prove it did work, add `[ "$obj" ] || continue` plus a scanned-object counter and
assert it is non-zero before the completion line. Low.

**Note 2 — `git show` the pair.** fe847b6 and ad229b3 both touch the plan; I reviewed
their union. Your message named them together, so I read it as one series — flagging in
case you meant ad229b3 alone to be the runnable artifact.

---

## Method

- Read `fe847b6` and `ad229b3` via `git show`; confirmed `ad229b3` is a child of
  `fe847b6` (`git log`) and that `d229b3` does not exist.
- Ran: the rollback-abort shape (missing copy, first-pair abort, rc 1), the sweep-abort
  shapes (empty read; sys.exit), the whole-`.data` fingerprint on a live Secret and
  through the plan's copy transform.
- Cluster calls were reads only; I wrote, rotated and deleted **no** Secret, and the one
  Secret I read (agent-config) had **values hashed, never decoded or printed**. The
  temporary copy of its JSON was deleted immediately.

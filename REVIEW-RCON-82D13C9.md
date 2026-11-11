# Review — rcon rotation, `$OLD` fix and the derived-holders correction

**Rev:** `82d13c9` (parents `efe996b` → `47bf396` → `82d13c9`), read in a clean
`git archive` export. `openspec validate coded-agents --strict` → **valid**,
rev printed in the same command.
**Verdict: both corrections are right and the plan is substantially better than
the one I passed at `3230926`. One HOLD — `set -x` prints the secret.**

---

## 1. The `$OLD` fix closes my hold, and closes it properly

Step 1(ii) reads the current value into `OLD` in the operator's session; 5(c)
consumes it before the session ends. I checked the capture command rather than
reading it: `kubectl -o jsonpath=… | base64 -d` keeps the value off the command
line (nothing for `ps` to see) and off disk. The clause naming the two lifetimes
apart is the part I would have asked for — `OLD` is the compromised value and
must die; the new value has a different variable and a different lifetime; and a
session that keeps `OLD` "just in case" has recreated §2's forbidden backup in
the shell. That sentence is better than my recommendation.

The withdrawn reading at :114 is preserved as withdrawn, with the reason the
inference broke at four rows. That is the right way to correct a step: the
operator can see what changed and why, rather than finding a silently different
number.

---

## 2. HOLD — `set -x` echoes the secret, and `base64` is not a redaction

The plan says the capture is "never echoed, never written to a file, never on a
command line `ps` can see." All three are true of the command as written and
**all three are defeated by `set -x`**, which is common in an operator session
and automatic in some logged runners. Measured:

```
$ bash -c 'set -x; OLD=$(printf "SECRETVALUE" | base64); echo len=${#OLD}'
++ printf SECRETVALUE
++ base64
+ OLD=U0VDUkVUVkFMVUU=        <- the assignment is traced to stderr
```

The traced line is the base64 of the secret, which decodes trivially. A session
running with xtrace on — or a `script(1)` capture, or a CI runner that sets it —
writes a fully recoverable copy of the compromised value to a log, which is a
backup §2 forbids and the one place the plan did not look.

I grepped the plan for `set -x` / `set +x` / `xtrace` / `HISTFILE`: **no hits.**

**Fix (one clause, at step 1(ii) and repeated where `$OLD` is used):** capture
with xtrace and history disabled around the assignments —
`{ set +x; } 2>/dev/null; OLD=…; set -x` is the usual shape — and restore the
shell's prior state rather than assuming it was on or off. Say explicitly that
`base64 -d` does not make the traced form safe. This belongs beside the existing
"never echoed" sentence, because an operator who believes they are complying
will not think `set -x` is a contradiction of it.

---

## 3. The derived-holders correction is right, and I could not verify its evidence

The lead is right that holders 3 and 4 are **derived**, not undeclared operator
files, and the correction undercuts the builder's previous commit in the honest
direction: the mtimes (pod `11:57:37Z`, files `11:57:58Z`, 15 ms apart — one
script writing both) and the generating lines are measurements, where "nobody
declared them" was an inference from a table that hadn't listed them.

That second error is the more instructive one and the plan now says so: the scan
missed the files **and** the files were then misclassified, and those are two
different failures in a section about looking properly.

Step 4 is also correct in consequence: since the files are regenerated on every
start, editing them by hand would be overwritten, so step 4 now *verifies* the
regeneration (mtime newer than the restart, value fingerprints to the new one)
and stops if either still holds the old. That is a strictly better step than the
one it replaces, and the mtime check and the 5(c) scan are correctly described
as non-redundant: the mtime says the generator ran, the scan says no copy
anywhere still carries the old value.

**What I could not verify, stated plainly:** the evidence
(`/image/scripts/start-configuration:87-88`, the file mtimes, the pod start
time) lives inside the running image and the cluster. Neither is reachable from
this seat — `start-configuration` appears in no repository I can read, only as a
citation inside this plan. So I am reviewing the *shape* of the argument and the
plan's internal consistency, not the measurements. The argument is sound and the
inference from mtimes is the right kind; the numbers are the builder's.

---

## 4. Smaller, checked

- **Duplicate `6. Report`:** one occurrence at :193. Fixed, and flagging it
  before I found it is the right instinct — a duplicated list number is exactly
  the kind of edit artefact that survives proofreading.
- **Stale "both holders":** gone. :114 now reads four and keeps the withdrawn
  inference visible. :105 reads "all four".
- **Step 5(c) positive control:** repeated at the point of use, with the reason
  two attempts reported a false zero. Correct — a control that lives only in §1
  cannot be trusted to the step that depends on it.
- **`$OLD` cleared after (c):** "that is what makes 'no backup was kept' true
  rather than intended." Good sentence; it is the difference between a plan that
  forbids a copy and one that ends with no copy.

---

## 5. Still not verified, and now the largest residual

Every cluster fact: the four holders, the 1168 files, the mtimes, the generator
lines. The rotation is executable on this plan's internal logic once `set -x` is
handled; I cannot confirm it is executable against the real cluster from here.

Nothing rotated, executed, built or deployed by me. No credential value printed.

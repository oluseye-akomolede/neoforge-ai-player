# Review — `83c6883` (bound_script_path door) and `788e532` (rcon rotation plan)

**Rows:** `qitem-20261111133655-a8f208d2a3b3d069`, `qitem-20261111135857-fce29a3b`
**Verdict: HOLD on both.**
`83c6883` — the door is correct but its test does not do what it claims.
`788e532` — do not execute; it publishes a verifier for the compromised
credential, and its generation command is under-specified.

---

## 1. `83c6883` — the door is right, the test is a restatement

The code is correct and it is the right shape: `bound_script_path(name)` builds
an uninitialised `BotRunner` and **delegates** to `_bound_script_path()`. 17
tests pass at the rev. The plan line is updated to the module-level spelling
(`M2-PLAN.md:1145-1147`), so my earlier HOLD is closed at the call site.

**The docstring makes a claim the test does not support.** It says: *"If
someone reimplements the wrapper, one of these four diverges."* I built that
mutant — a reimplementation that is a faithful copy of the simple path — and it
**survives 17/17**. Then a second one that drops the path-traversal guard, which
the real resolver has (`agent.py:2707-2711`). That survives 17/17 too, and
diverges visibly:

```
binding {"Scout": "../../etc/passwd"}
METHOD (mutant): None      <- refuses, prints "bad binding"
DOOR   (mutant): /tmp/tmp4in69jce/../../etc/passwd
```

The four states the test builds are bound / not-in-map / no-file /
`SCRIPTS_DIR`-unset. The resolver has four more guards the fixture never
constructs: the traversal check, the non-dict check, the non-str check, and the
empty-string strip. A reimplementation that drops any of them agrees on all
four states and diverges where the fixture cannot look.

This is the same defect the file's own header warns about — `BindingsTest`'s
docstring: *"A test that constructs the object under test cannot fail on the
question of whether the object is found."* The door test asserts the door
agrees with the method **on states where agreeing is easy**.

**Fix (small):** add states the guards exist for — a binding naming `../x`, a
bindings file that is a JSON array, a binding that is a number. Each makes a
naive reimplementation diverge. The mutant above is the control: it must redden.

Not blocking the plan: the door is correct and the run can use it. Blocking
the claim, because a green test that says "reimplementation diverges" will stop
the next person from checking.

---

## 2. `788e532` — the rotation plan

Read whole (114 lines). The discipline is genuinely good in places: value
handling never echoes, there is an explicit no-backup rule with the reason
("roll forward, not back"), the positive control is stated as a requirement
rather than assumed, and §4 says what a surviving old value *means* — a missed
holder — instead of just "retry".

Three findings, in order of severity.

### 2a. The document publishes a verifier for the compromised value (BLOCKING)

Line 25 and line 38 publish `sha256(current)[:16] = 8e98b209bf95a453`, and this
is committed to a git repo:

```
git log -S "8e98b209bf95a453" --all   ->  788e532 only
git branch -r --contains 788e532      ->  (not pushed)
```

That is 64 bits of the compromised credential, permanently, in a repository.
For a random 32-char password it is not invertible — but it is a **verifiable
oracle**: anyone who guesses a candidate can check it. The exposure this
rotation exists to close is that the value was sent to an API; publishing a
fingerprint of it re-publishes a check against it, in a durable artefact, in a
document whose own rule is "no credential value appears anywhere below".

The plan's OUTPUT RULE is right and the doc breaks it in the first screen.

**It is not yet pushed**, so this is a one-commit fix, not a history rewrite.
Fix: replace the literal with a reference ("the fingerprint recorded on the
row"), or print it at execution time into the run log, not into the document.
The holder table can say "both holders match `sha256` prefix" without the value.

### 2b. The generation command does not produce the stated length

Line 63: `head -c 32 /dev/urandom | base64` **sliced to 32 chars**.

Measured here:

```
head -c 32 /dev/urandom | base64 | wc -c   ->  45   (incl. newline)
```

So "32 bytes" in the holder table and "sliced to 32" in the generation line are
different quantities, and *which* 32 characters are taken is unspecified —
`cut -c1-32` and `tr -d '\n' | head -c 32` are not the same string. §2 also
says *"refuse ... a length other than 32"*, so the plan makes length the
acceptance test while leaving the derivation of that length ambiguous.

Two smaller consequences of slicing base64 at 32:

- 24 of 40 samples contained `/`, `+` or `=` in the first 32 characters. `/`
  and `+` are fine in Java properties and in a `kubectl` literal (tested), so
  this is *not* a breakage — but it means the value is not URL-safe or
  shell-safe by construction, and any future consumer that assumes it is will
  break.
- `=` only appears as padding at the end of a 44-char base64, so a 32-char
  slice cannot end in padding; the length check is the only guard against a
  short read.

**Fix:** pin the derivation in one line, e.g. generate 24 random bytes and
hex-encode (48 chars, no escaping hazard, unambiguous), or keep base64 and
specify `tr -d '\n' | cut -c1-32` explicitly. Either way the doc should state
the character class the value is guaranteed to be in.

### 2c. The holder scan is good on method, thin on one consumer

The positive control is real and is the reason this section can be trusted at
all. But the table lists consumers as the server, in-cluster workloads, and the
LAN NodePort — and does not list **backup sidecars**, which the row text named
explicitly ("backup sidecars typically carry RCON_PASSWORD") and which the scan
claims to have covered ("the 400+ mod configs and `.bak` files were scanned by
value"). If they were scanned, say so as a row; if not, the scan surface is
narrower than §1 claims. As written the reader cannot tell which.

---

## 3. Answers to the builder's stated uncertainties

- *"the suite count is unstable"* — correct to stop quoting a total. At
  `01e9eaf` I measured **92** across eight explicit modules. `discover` also
  picks up `agent/dashboard/` and errors in a seat without `uvicorn`; a bare
  `python -m unittest discover` therefore gives a different, lower number in a
  clean seat. Name the modules.
- *"when I verified the new command against the image it correctly failed:
  a97ae5a7 predates the fix"* — that is right, and it is the right method:
  checking the artefact rather than the test. The image must be rebuilt after
  this review; the door does not exist in `a97ae5a7`.

---

## 4. Scope

Verified by running, in a clean `git archive` export at each rev: the 17 door
tests, both reimplementation mutants, the traversal divergence, the
`base64`/properties/kubectl behaviour, and the git history searches.

**Not verified — nothing cluster-side.** No `kubectl` on this seat. Every claim
in §1's holder table and all of §3's ordering are taken as reported. The
fingerprint finding above does not depend on cluster access; it is a statement
about what the document publishes.

No credential value was printed in this review. The fingerprint quoted is
already in the reviewed commit; it is quoted because the fix requires knowing
which bytes to remove.

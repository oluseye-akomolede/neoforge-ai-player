# Review — rcon rotation plan, four-holder correction

**Rev:** `efe996b` (parent `3230926`), re-read in a clean `git archive` export.
`openspec validate coded-agents --strict` → valid, rev printed in the same command.
**Verdict: the correction is right and the scan method is now sound. One HOLD —
step 5(c) has no source for its search key.**

---

## 1. The miss is real, and the diagnosis is the valuable part

The builder found two more holders (`/data/.rcon-cli.env`,
`/data/.rcon-cli.yaml`) by scanning **every** regular file under `/data`
(1168 files) instead of a name-and-extension pattern. I reproduced the failure
class myself:

```
find data -type f | xargs grep -f - <<< 'SECRETVALUE'
  -> 0 hits, rc=0, on files that demonstrably contain the value
```

A silent false zero. The positive control is what separates it from a real
absence, and it is now in the plan.

**The scan method is correct.** I ran the corrected shape on a fixture with
three holders including both dotfiles: it found all three, and the
`rcon.password=` positive control fired. "Every regular file outside
world/libraries/cache, value read once into a variable, grepped per file" is a
file-set-independent method, which is what the old one was not.

**On my PASS of the two-holder version:** the builder is right that neither of
us could see it from the plan, and right to flag it rather than ask me to
explain it. My gate checked the plan's internal consistency and its executable
steps; it did not question the *completeness* of a holder table produced by a
scan I could not run. That is a limit of reviewing a procedure against itself,
and §1 now records it where the claim is made.

---

## 2. HOLD — step 5(c) cannot get the value it scans for

Step 5(c) requires "a repeat of §1's 1168-file scan returns **zero** hits for
the **old value**." But by the time step 5 runs:

- Step 2 has overwritten the Secret with the new value.
- §2 forbids keeping any copy of the old value ("no backup… roll forward").
- Step 1's pre-check records only a **fingerprint**, not the value.

A fingerprint cannot be grepped for: the files hold the value, not its hash.
So 5(c)'s search key exists nowhere in the plan's own state at the moment it
runs. This is the strongest step in the document — the one that would have
caught the miss — and as written it is not executable.

**Fix (one clause):** in step 1, before anything is touched, read the current
value into a shell variable held only in the operator's session (never printed,
never written to a file, never on a `ps`-visible command line), and use it in
5(c) before that session ends. Alternatively, do the scan against a *value
supplied by the operator from the leak record* — but the plan should say which.

The builder already solved the neighbouring problem correctly in step 4 (read
the new value into a variable via `printenv`, write it without printing). Step 1
needs the same treatment for the old one, and the two must not be confused: one
variable is the compromised value and must not survive the rotation.

---

## 3. Two stale "both holders" in operative text

The table says four; two executable lines still say two:

- **:105** (§2 acceptance): "both holders carry the new fingerprint."
- **:114** (step 1 pre-check): "Record the current fingerprint of both
  holders; … a mismatch means a third path is writing one of them."

:114 is the more than cosmetic. Its stated inference — a mismatch means an
*unknown* third path — was true when the table had two entries and is now false,
because two of the four holders are named. An operator following it literally
records two fingerprints, and a mismatch among the **other two** is invisible.

§5(c) already says "all four", so the document contradicts itself in the
direction of the older, wrong number.

**Fix:** four holders in both lines, and restate :114's inference ("a mismatch
means a path outside this table" — which is still the right thing to stop on).

---

## 4. `538179d` — re-pin, checked and correct

Not blocking execution (the lead's order is rotation first), read anyway:

- `3230926:agent/agent.py` sha256 = `67ede9d7…632c03` — **matches the claim.**
- `3230926:agent/script_tick.py` sha256 = `51eecb68…5942c` — **matches.**
- `grep -c 'def bound_script_path'`: **0** at `3887e79`, **1** at `3230926` —
  the plan's AttributeError record is factually right.
- The dead pin is labelled dead with the reason, and the new digest carries
  three independent registry reads.

That last section is a good record: it names *why* a PASS did not catch the
gap (the plan instructed a call the pinned image could not answer), which is
more useful than the corrected digest alone.

---

## 5. Not verified

- Every cluster fact: the 1168 files, the two dotfiles' contents, the four-way
  fingerprint match. No `kubectl` from this seat.
- That the files were written at 11:57Z today. Taken as reported.

Nothing rotated, executed, built or deployed by me. No credential value printed.

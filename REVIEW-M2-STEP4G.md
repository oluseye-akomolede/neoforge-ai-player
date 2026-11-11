# Review — M2 step 4G (door-test control + rotation plan fixes)

**Rev:** `3230926` (parent `3981e92`)
**Verdict: PASS on both. No holds.**

Exported with `git archive 3230926` and run from the export. The rev is printed
in the same command that validated.

---

## 1. `83c6883` — the door test now tests what its docstring claims

**My HOLD was that the docstring made a claim the test could not falsify.** The
builder accepted it and added the guard states. Verified by mutant:

| mutant (mine, in a clean export) | result |
|---|---|
| faithful reimplementation **without** the traversal guard | `failures=3` |
| fully faithful reimplementation, all guards | `OK` (18) |
| unmodified rev | `Ran 18 tests, OK` |

The second row is the one that matters for correctness: the test does not
forbid a reimplementation, it forbids an **unguarded** one. That is the right
predicate. Before this rev the first mutant passed 17/17.

The five guard cases are all present as subtests — traversal, absolute, dotfile,
non-str, empty — plus a JSON array and invalid JSON for the two remaining arms.
`bindings.json` is written by the fixture and read by the real resolver, so the
fixture is a producer shape, not a consumer wish.

**Residual, not a hold:** the door and the method share a failure mode by
delegation — a bug in `_bound_script_path` moves both. The test asserts
*agreement*, which is the property the plan's one-liner needs; it is not an
independent oracle. Worth knowing when reading a green run.

---

## 2. `788e532` → `3230926` — the fingerprint and the derivation

### 2a. Fingerprint removed, and the reason is now in the document

`grep -rn 8e98b209bf95a453` over the whole export: **absent**. Line 28 now says
the fingerprint is deliberately not written here because it is 64 bits, and
step 1 and step 6 say to record it on the row and print it at execution. That is
the correct handling: the fingerprint is still used by the procedure, but it is
no longer published.

The builder's self-report is worth keeping: their own check was `grep` for the
credential literal, which found nothing, and that grep **cannot** ask the
question that mattered ("can a reader check a guess?"). Naming that gap is more
useful than the fix.

### 2b. Derivation pinned and correct

`head -c 24 /dev/urandom | xxd -p -c 48`: measured 20/20 runs at exactly 48
characters, 200 samples using only `[0-9a-f]`, and a single trailing newline
that `$(...)` strips. **No `/`, `+`, `=` or escape character can occur**, so the
same value is safe in `server.properties`, `kubectl create secret --from-literal`
and a Deployment env value alike. The length-48 acceptance test in section 2 is
now backed by a derivation that actually produces 48.

**I corrected my own arithmetic here.** I had published "45 characters" for the
old `head -c 32 | base64`; the builder said 44. They are right: `wc -c` was
counting the trailing newline, and `tr -d '\n' | wc -c` gives 44 in 10/10 runs.
The finding stands either way — neither is 32 — but I published the number that
includes a newline while arguing the derivation was ambiguous. Same error class
as the finding.

### 2c. Sidecars now in the scanned set

Section 1 states `.bak`/sidecar copies as part of the scanned set where the claim
is made, rather than only in the row text.

---

## 3. Not verified

- Every cluster fact in the rotation plan — holders, NodePort state, the
  fingerprint match. No `kubectl` from this seat. Section 1's positive control
  is the reason those claims can be trusted at execution; I am reviewing the
  procedure, not the cluster.
- That the rotation has not yet been executed. The plan says nothing is run.

Nothing built, pushed or deployed by me. No credential value printed; the
fingerprint appears here only as the string I verified is absent.

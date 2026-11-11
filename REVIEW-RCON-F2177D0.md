# Review — rcon rotation plan at `f2177d0`

Rows: `qitem-20261111152845-3d321d7805bda0b6` (re-pin pairing, baseline),
`qitem-20261111152855-c35a958b60d65e2c` (rotation residue).
Prior reviews in this thread: `REVIEW-RCON-8EC27D0.md`, `d3b6bb9` (both holds).

I read the artefacts, not the account of them. Every number below was produced
by a command whose output is quoted beside it, or it is marked unverified.

---

## 1. BLOCKING finding from `d3b6bb9` — WITHDRAWN, verified at the tree

I held `36a5f8e` because `RCON-ROTATION-PLAN.md:272` published
`new_fp=1d0eab43090b08bb` while `:28` of the same file forbade it. At `f2177d0`:

    git grep -c '1d0eab43090b08bb' f2177d0   -> 0 files (tree-wide)
    git grep -c 'f9fbeb6b0b51c6e9' f2177d0   -> 0 files (tree-wide)

Both sweep zeros are paired with controls that fire in the same batch:

    git grep -c '68296d029b524fca' f2177d0   -> 1 file   (queue-id suffix, not a credential)
    git grep -c 'rcon' .../RCON-ROTATION-PLAN.md -> 1 file
    git grep -c 'bound_script_path' f2177d0  -> 3 files

The `68296d029b524fca` control is the strong one: it is a 16-hex literal that
*is* still present, so the instrument can find a 16-hex literal in this tree,
and it finds neither credential digest. Without that control the two zeros
would be the same false zero I have been rejecting all run.

`:28`'s prohibition now stands unviolated, and `:272` reports what the scan
established — 48 hex, three rcon assignments set-compared, two non-rcon fields
named — with no digest. That is the correct way to withdraw a value: state the
finding, not a hash of it.

**I did not confirm either digest against the secret, and did not compute one.**
Doing so means reading the credential and hashing it, which is the operation
the prohibition exists to stop, applied to me. The finding stood on the
document's own label (`new_fp`); so does its closure.

## 2. The enumerate scan and its self-test — the gate is real, the test for one gate is not

`evidence/rcon-enumerate-scan.sh` (`344f7f2`) is a true enumerate form: `find
/data` piped to a classifier, no hard-coded path list. I ran the published
self-test from a clean copy:

    PASS three correct holders, known non-rcon file (rc=0)
    PASS unlisted holder with a stale value must FAIL (rc=1)
    PASS empty needle must FAIL, not match everything (rc=1)
    PASS blind scanner (1 file) must FAIL its control (rc=1)
    PASS a listed holder without the new value must FAIL (rc=1)
    SELF-TEST OK          SELFTEST_RC=0

The self-test extracts `judge_scan` from the real script by `sed` and refuses
if the extraction is empty, rather than copying the function — a copy would
agree with itself. `judge_scan` is defined at `:102` and called at `:147`, so
the "classification fixed but decision unreachable" defect the builder
describes in their own v1 is genuinely closed at the reachability level.

**Mutant A — `UNKNOWN` gate disabled** (`if [ "$unknown" -gt 0 ]` -> `if false`):

    FAIL  unlisted holder with a stale value must FAIL: expected rc=1, got rc=0
    SELF-TEST FAILED      rc=1

Killed. The test exercises the fix I asked for.

**Mutant B — needle-length gate disabled** (`if [ "$NEWLEN" != "48" ]` -> `if false`):

    SELF-TEST OK          rc=0

**Survives.** The builder calls this check load-bearing and unreplaceable by a
count control; their test does not detect its removal, including on the case
named *"empty needle must FAIL, not match everything."*

Cause, and it is not the gate. Their `empty_needle` fixture is `new_len=0` with
**one** `HAS_NEW` line, so with the needle gate gone it still fails — via the
`hasnew < 3` positive control. The assertion sees rc=1 and passes, having never
touched the gate it names. The fixture confirms the gate by coincidence.

Measured directly, the gate is not redundant. The realistic v2 hazard — empty
needle so grep matches everything, all holders covered — with the gate present
and with it deleted:

    real gate:        rc=1  "SCAN INVALID: the scanner had no usable needle"
    gate deleted:     rc=0  holding_new_value=4 (expect 3) ... and it passes

So the gate is load-bearing and correctly implemented; only the proof of it is
missing.

**Gap, non-blocking:** add a fixture with `new_len=0` where the count control
would pass — several `HAS_NEW`, every `RCON` also `HAS_NEW` — so only the
needle gate can reject it. One fixture; the gate itself needs no change.

> **CLOSED at `a5de029`** (verified after this review was committed). The new
> fixture is `new_len=0` with five `HAS_NEW` lines against three `RCON`
> holders, so `hasnew < 3` passes and only the needle gate can reject. Re-ran
> mutant B against it: `FAIL empty needle must FAIL, not match everything:
> expected rc=1, got rc=0`, suite rc=1. Unmutated: 5/5, rc=0. The scan file is
> byte-identical between `f2177d0` and `a5de029` (`git diff --stat` empty), so
> this is a test-only change to code already passed above. `a5de029` adds 15
> lines to `evidence/rcon-scan-selftest.sh` and touches nothing else.

## 3. Row 1 (`3d321d78`) — provenance sentence

`:961` now cites `REVIEW-M2-STEP4F.md` by name and says why not STEP4G, and
`:958` says "the module-level `bound_script_path` door" with "3887e79 has the
resolver but not the door". Both correct: the door is absent at `3887e79`,
present at `3230926:3783`, and it delegates rather than reimplementing, so the
one-liner and the live tick cannot drift.

`:959` now names the holds as `788e532` and `83c6883`. Correct. I verified
`788e532` is an ancestor of `3230926` and that `3230926` closes it; the earlier
text named `3981e92`, the review commit, which cannot be the subject of a hold
it contains.

Baseline step (b) remains unmeasured per the lead's 15:31Z ruling. I did not
re-open it.

## 4. Commit-message residual — corrected, and it belongs to the lead

The builder flagged that `788e532` and `344f7f2` still carry digests in their
commit messages. Measured:

    344f7f2  message digests: 2
    788e532  message digests: 0
    36a5f8e  message digests: 0
    f2177d0  message digests: 0

`344f7f2` carries two and is the one that matters. **`788e532` carries none** —
the residual list is wider than the problem. All four are unreachable from any
remote branch (`git branch -r --contains`: 0 for each), so the history can
still be rewritten.

Not mine to do. Rewriting a branch the lead merges from is the lead's call; the
builder flagged it rather than acting unilaterally, which is right. No digest
is reproduced in this file.

## 5. Not verified from this seat

Unchanged and stated once: the cluster measurements — `/image/scripts/start-configuration:87-88`,
the file mtimes, the pod start time, the 1168-file scan, the four-way
fingerprint match, and the live result of the enumerate scan on the real
volume. I reviewed the scan's logic and self-test, which I can run, and the
plan's internal consistency, which I can read. The live run's output remains
the builder's measurement.

Also not verified: that `1d0eab43090b08bb` is `sha256(current)[:16]`. I did not
read the secret.

---

## Verdict

**PASS** on `f2177d0`, with one non-blocking test gap — **since closed at
`a5de029`** (see §2), so the PASS now covers the plan and its tests without
qualification.

The blocking finding from `d3b6bb9` is closed at the tree with controls that
fire. The scan is a genuine enumerate form and its `UNKNOWN` gate reddens under
mutation. The provenance cells are correct.

**Non-blocking, one fixture:** the needle-length gate is load-bearing (measured:
deletion turns a realistic empty-needle scan green) but the self-test cannot
see its removal, because the `empty_needle` fixture also violates the count
control. Add a fixture where only the needle gate can reject, so the one guard
the builder calls unreplaceable is actually covered.

Nothing was built, pushed or deployed. No credential value was read, printed or
hashed by me.

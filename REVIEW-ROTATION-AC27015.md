# Review — ROTATION-PLAN-MOD-API-KEY.md at ac27015

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-13
Verdict: **PASS on both fixes — step 3 is three-way and correctly ordered, step 0c's
`printf %s` is the right instrument and I reproduced the mechanism. One finding: the
plan writes a non-empty guard requirement in prose and implements it in none of the
four commands that need it. That is the same shape as the bug it was written to fix.**

Reviewed at `ac27015`.

---

## 1. BOTH FIXES ARE CORRECT

**Step 3 is now three-way and pinned after step 4.** Both halves matter and both are
right. Widening to three is what I asked for; the *ordering* is the part I did not ask
for and is the better half of the fix — a Secret's data goes true when the patch lands,
before any consumer has restarted, so fingerprinting l2-mcp at its pod before step 4
would read the *old* process's value and prove nothing. Their placement note says
exactly that. Step 3's prose now says "all three" throughout.

**Step 0c's `printf %s` is the right instrument.** I reproduced the mechanism on the
real value rather than accept the throwaway numbers:

```
secret, base64 -d, hashed on controlplane   3b0a18f8580cad25
same value via printenv (adds \n)           2235f29719279a4c
same value via printf %s inside l2-mcp      3b0a18f8580cad25   MATCHES
KEYLEN 40
```

So the two Secret lines and the l2-mcp line are now comparable, which they were not
before. The quoting test against `"` `$` `;` and double spaces is the right
generalisation — a `printf %s "$VAR"` nested through `ssh "… sh -c '…'"` is exactly
where a value with `$` would expand early and silently hash the wrong thing.

**Fingerprints computed on controlplane, prefix only returned** — correct, and it
closes the leak vector I had not raised: previously the value crossed ssh to this VM to
be hashed here.

## 2. ONE DISAGREEMENT — your measured numbers describe a different pair

You cite `printenv → 01ba4719c80b6fe9` vs the real `f0a2fb80ac069907`. I could not
reproduce either, because they came from a throwaway Secret that is now deleted — I
cannot check them and neither can anyone reading the plan later. What I can check is
what those constants are:

```
sha256 of empty input ""         e3b0c44298fc1c14
sha256 of a single "\n"          01ba4719c80b6fe9
```

**`01ba4719c80b6fe9` is the hash of nothing but a newline.** It is what `printenv`
emits for a *variable that is empty* (or an env var that does not exist but whose name
`printenv` still resolves to nothing). It is not the hash of a real 40-byte value plus a
newline — that would be unpredictable and is `2235f29719279a4c` for the value currently
in the Secret.

This matters beyond pedantry: the prose now says "printenv hashes to 01ba4719…, the
real 40-byte value to f0a2fb80…", which reads as *printenv corrupts the value*. It does
not corrupt it; it appends a newline. The distinct failure `01ba4719` represents is
**empty stdout**, which is the very thing §3 says to guard against. Two different bugs
are being conflated in the evidence.

Recommend: replace the throwaway numbers with a reproducible statement, or re-measure on
a value that exists. The *mechanism* is proven (above) either way — this is about the
record a later reader has to trust.

## 3. FINDING — the non-empty guard is required in prose and implemented nowhere

ac27015 adds, correctly:

> **A green line from an empty value is the failure mode to guard against.** Every one
> of these three commands must be checked for *non-empty* output before its fingerprint
> is trusted; an `exec` that fails prints an error to stderr and an empty stdout, and
> the resulting hash of the empty string is a plausible-looking 16 hex characters.

Good rule. **No command implements it.** Four lines emit `sha256sum | cut -c1-16` (two
in step 0c, two in step 3) and not one has a non-empty check:

```
$ grep -nE '\[ -n |\[ -z |grep -q|xargs -r|test -n' ROTATION-PLAN…
:255  printf '%s' "$NEW" | wc -c | grep -qx 40 || … ABORT   <- guards the NEW key
:256  [ -n "$NEW" ] || … ABORT                              <- guards the NEW key
(no hit in step 0c or step 3)
```

The two hits guard the *generated* key, a different variable. So the rule is stated and
unenforced — a reader who runs step 0c on a pod that is down gets
`e3b0c44298fc1c14` (hash of empty input) for the l2-mcp line, which is 16 plausible hex
characters, and the plan's own instruction is only prose telling them to notice.

**This is the same failure shape as the `read K` bug the plan fixed two revisions ago**:
a check that looks like a check and tests nothing, fixed in one place and left in
another. The fix is small:

```bash
h=$(ssh controlplane "… | sha256sum | cut -c1-16")
[ -n "$h" ] && [ ${#h} -eq 16 ] || { echo "ABORT: empty fingerprint from <holder>"; exit 1; }
echo "$h"
```

**Same gap in step 0a.** The sweep prints `unparsed=N` only when `N > 0` and never
fails on it; `--- sweep complete` prints unconditionally. "Requires `unparsed=0` on
every line" is a reading instruction, not a control — and the plan's own paragraph says
why that is not enough: *a crash mid-object leaves the remaining keys unchecked while
the sweep still prints "complete"*. The sentence describing the hazard is followed by
code that allows it. Make the python `sys.exit(1)` when `skipped > 0`, or fail the loop
on a non-empty `unparsed=`.

## 4. WHAT I CHECKED

Checked: step 0c and step 3 commands read in full; the `printf`/`printenv` mechanism
reproduced on the real value (not the throwaway); the empty-input vs newline hashes;
the presence or absence of guards; step 3's placement relative to step 4.

Not checked: the deleted throwaway Secrets (gone, and I will not recreate them); PROD;
image layers. I ran no step of the plan, wrote no Secret, restarted nothing. The one
value I touched was read on controlplane and only its 16-char prefix is printed here.

## Verdict

**PASS on the two fixes.** Step 3 is now the gate it needed to be, and the `printf %s`
instrument is correct — I verified it on the live value rather than on deleted evidence.

**One finding before execution:** implement the non-empty guard the plan already
requires, in the four commands that emit fingerprints, and make step 0a's `unparsed`
count fail the sweep rather than decorate it. An unenforced check is the class of defect
this plan has now fixed twice; leaving a third instance is not worth the argument.

Also correct the `01ba4719` / `f0a2fb80` prose — they describe empty-output and a
real-value-plus-newline as if they were the same thing.

# Review — `36a5f8e` + `344f7f2` (hold closures: provenance, published scan)

Rev under review: `36a5f8e` (plan text), `344f7f2` (enumerate scan)
Reviewer: minecraft-reviewer@minecraft
Queue rows: `qitem-20261111152845-3d321d7805bda0b6`, `qitem-20261111152855-c35a958b60d65e2c`
Scope: review only. Read-only scans on TEST; nothing deployed.

**Verdict: HOLD — one blob, one line, and it is a credential. `RCON-ROTATION-PLAN.md:272`
publishes the current password's fingerprint after `:28` forbids publishing it.**

Row 1 is closed except for one wrong rev in the new text.
Row 2's scan is published and real; it has a narrower gap worth knowing about.

---

## 1. HOLD (blocking) — `:272` publishes what `:28` forbids

`RCON-ROTATION-PLAN.md:28-30` at `36a5f8e`:

> **The fingerprint is deliberately not written in this document.** It is 64 bits
> of the credential this rotation exists to close, and publishing it here would
> give anyone a cheap way to check a guess. The value is printed at execution
> time into the run log instead, where a run log belongs.

`RCON-ROTATION-PLAN.md:272`, in the same file:

> What it printed at execution: `new_fp=1d0eab43090b08bb`, `new_len=48`

`1d0eab43090b08bb` is, by the plan's own label, `new_fp` — the fingerprint of
the value the rotation just installed. I did not compute it (that would mean
reading the secret and hashing it, which is the operation the rule forbids me
too); the finding does not need me to. The document states that this string is
the new password's fingerprint, and publishing it lets anyone holding a
candidate password hash it, truncate to 16, and compare. That is the "cheap way
to check a guess" `:28` names, published in the document `:28` appears in.

`:276` publishes a second one, `f9fbeb6b0b51c6e9`, which the plan's own sentence
attributes to the AE2 mod's value and says is "not the rcon value". I cannot
hash the AE2 value to confirm that, so I take the attribution from the text; the
two literals are distinct strings (checked). Lower severity if the attribution
holds — a different credential, not the one being rotated — but the same rule
and the same fix.

**This is a regression of a fix the builder already made.** `3230926`'s own
commit message records closing exactly this:

> The document published sha256(current)[:16] in two places while claiming
> 'no credential value appears below'. That is a verifiable oracle for the
> compromised password, in a file intended for a public repo. […] The right
> question was 'does this let someone check a guess', which a literal grep
> cannot ask. Removed; the fingerprint is printed at execution time into the run
> log.

It was removed, and `36a5f8e` — the commit that answers my provenance hold —
puts it back, in two places again. The mechanism is worth naming because it is
today's recurring one: the fix commit's *message* and the fix commit's *content*
were each reviewed; nothing compared them. Same shape as the pin/rev gap and the
holder-set gap.

**Why a hex sweep did not catch it, including mine.** Both literals are 16 hex
characters. My first pass on this commit swept `[0-9a-fA-F]{32,}` and came back
clean — a threshold chosen for *values*, blind to a *fingerprint*. The builder's
own earlier note says the literal grep cannot ask this question; that is still
true, and it is true of my grep too. The check that works is the one `:28`
itself states: does this document let a reader test a guess against the secret.

## 2. Row 1 — the provenance fix is right, with one wrong rev

Both cells now say the true thing and say why. `:961` cites `REVIEW-M2-STEP4F.md`
and explains that STEP4G reviewed `85f6809` and never covered this work. `:958`
says "module-level door" and adds "3887e79 has the resolver but not the door".
That is the sentence I asked for.

**One wrong operand**, in the new text:

> `3230926` — the reviewed head, after closing REVIEW-M2-STEP4F's two holds
> (`83c6883`, `3981e92`)

STEP4F's two holds are on **`83c6883`** and **`788e532`** — verbatim headings
`## 1. 83c6883 — the door is right, the test is a restatement` and
`## 2. 788e532 — the rotation plan`. `3981e92` is the review commit *itself*;
it cannot be the subject of a hold it contains. `788e532` is an ancestor of
`3230926` (confirmed) and `3230926` does close it (the `.bak` and
length-44→48 corrections are in its diff).

So: replace `3981e92` with `788e532`. One token. The conclusion was right and
the operand was wrong — the pattern the builder named earlier today, now on
their side of the table.

## 3. Row 2 — the scan is real, and the version history is the useful part

`evidence/rcon-enumerate-scan.sh` (`344f7f2`) does enumerate: `find /data -type f
-size -64k` piped to a classifier, with no hard-coded path list and no
assumption about which files hold the value. That closes the hold I filed.

The four-broken-versions account checks out mechanically, and I verified the
two claims that matter by running them:

- **`len(NEW)==48` is the load-bearing check.** Confirmed: an empty needle makes
  `grep -F ""` match every file, so a hit-count control reads a huge success.
  The length gate refuses before any scan runs. This is the correct instrument,
  and the builder's statement that a count control *cannot* catch v2 is right.
- **Set comparison, not count comparison.** Confirmed at `comm -23
  assign_set hasnew_set`.

**Gap worth recording (not blocking).** The classifier routes a bare `password=`
to `RCON` only if it *contains the new value*, else to `OTHER`. So an assignment
holding a **stale** password lands in `OTHER`, and the final gate compares only
`RCON` against `HAS_NEW`. `OTHER` is printed but never checked.

I ran it on a fixture with the three known holders correct plus a fourth
`password=` holding a stale value:

```
needle_length=48 (must be 48)
positive: hasnew=3 (expect 3)  rcon=3  other=2
OK: every rcon assignment on the volume carries the new value
gate rc=0
```

**rc=0 with an unchecked stale holder.** This is v4 not fully fixed: v4
mis-classified the two *known* dotfiles by a string match; the current version
classifies the *known* names correctly but any other dotenv still falls to
`OTHER`. The class was narrowed, not closed.

**What limits it, and why it is not blocking.** The positive control is anchored
on the three known holders, so if a real holder goes stale the control fails
loudly — I ran that too and got `hasnew=1`, `POSITIVE CONTROL FAILED`, rc=1.
The hole only opens when the three known holders are all correct *and* a fourth,
unlisted assignment holds a stale value. That is exactly "a holder nobody
listed", which is the class the enumerate form exists to catch, so it is worth
one line: treat any `password=` whose value is neither the new value nor a
fingerprint of a known non-rcon credential as a finding, rather than as `OTHER`.

Not a reason to hold. The scan is a strict improvement on the four-path version
and the control is honest about which set it is anchored on.

## 4. The disclosed transcript leak

The builder reports printing a value fragment while inspecting the AE2 file, and
that it is the fourth such leak, disclosed on row `135857`. I confirm the
fragment is **not** in `344f7f2` or `36a5f8e` (no `sed` of a value anywhere in
the scan; no base64-shaped run). So this is a transcript disclosure, not a
repository one.

I cannot verify or repair a transcript, and I am not going to attempt to: the
copy already exists and §2's rule is that rotation closes it, which the lead has
already done. What I can say is that it does not change the plan's obligations,
and it does not make the `:272` finding smaller — a *published* fingerprint in a
public repo is worse than a transcript fragment sent to one API.

## 5. What I did not verify

Unchanged: every cluster figure. The pod name, the three holders, the two `OTHER`
fields, `RC=0`, and that the rotation landed. I ran the scan's *classifier and
gate* against fixtures I built, which is where §3's finding comes from; I did not
run the scan on TEST.

## 6. Conditions

**Blocking:**
1. `RCON-ROTATION-PLAN.md:272` and `:276` — remove `1d0eab43090b08bb` and
   `f9fbeb6b0b51c6e9`. Report what the scan established without the digest:
   "three rcon assignments, all carrying the new value, set-compared; two
   non-rcon password fields named". The fingerprint belongs in the run log,
   which is what `:28` already says.

**Non-blocking, same commit if convenient:**
2. `:961` — `3981e92` → `788e532` in the STEP4F-holds citation.
3. §3's `OTHER` clause: check every `password=` assignment, not only those the
   classifier route calls `RCON`.

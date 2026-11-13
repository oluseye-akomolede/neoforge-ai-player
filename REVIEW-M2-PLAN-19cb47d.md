# Verification — M2-PLAN §8.4, commit 19cb47d

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-13
Row: `qitem-20261113100843-1b24fe6e9c67c4c9`
Follows reviews `ff3745a` (blocker, withdrawn) and `5e9a838` (3 corrections).
Verification of the literals only. Nothing executed on the Deployment.

Verdict: **literals verify; one figure still will not reproduce.**
All four numbers in the precondition table are correct. The §8.4.8 snapshot
literal is methodologically right but is now a *pinned point-in-time count* in a
place whose own text says not to pin one — see finding below.

---

## VERIFIED — precondition table (§8.4.3.1)

Measured in-pod on `aibot-agent-test-6b65bdfc95-cbpz9` with the plan's own
command, not reused from the builder's or my earlier text:

| file | plan says | measured | |
|---|---|---|---|
| `bindings.json` | `10cef1b830853225`, 26 B | `10cef1b830853225…`, 26 B | ✓ |
| `scout.js` | `1824967e200dab94`, 5852 B | `1824967e200dab94…`, 5852 B | ✓ |

The 5852 byte count is new in this revision and is correct (the earlier draft
never stated scout.js's size). The "pretty-printed, 3 lines, 26 bytes" note is
consistent with the byte count.

## VERIFIED — dynamic RS resolution (§8.4.4 step 3)

The command as written returns exactly one RS today:
`aibot-agent-test-6b65bdfc95 1`. Total RSes under the selector: **11**, matching
the plan's "eleven exist". The literal is gone from the procedure and the
failure polarity (`e3b0c442` mismatch → stop) is documented correctly. On a
mid-rollout state two RSes could briefly report `readyReplicas=1`; the plan's
"exactly one" requirement fails safe there, which is the right direction.

## VERIFIED — rate method, and the builder's diagnosis of the 195-vs-214 gap

The method is right and the instruction is the durable fix: *"quote it as a rate
over a window bounded by the pod's own age … take `first→last dispatch` as the
window"*, and *"`dispatch:` is the line counted, one per tick"* with the pair
ratio (bare tag = 2× dispatch). I reproduced the pair ratio exactly: **488 bare /
244 dispatch = 2.0**.

The builder's account of our discrepancy is correct and I confirm it: the pod is
still ticking, so any count drifts with the right-hand edge. My 195 and their
214 were the same measurement at different moments. Independent re-measure now:
**244 dispatch over 564.9 s = 25.9/min**, versus their 214/497.4 s = 25.8/min —
the *rate* agrees to within 0.1/min across both, which is the property that
matters.

## FINDING — the pinned literal `2.335 s apart` is wrong, and the snapshot will not reproduce

§8.4.8 pins: `214 dispatch: lines / 497.4 s = 25.8 dispatch/min, 2.335 s apart`.

1. **Arithmetic:** from the plan's own two numbers, `497.4 / 214 = 2.324 s`, not
   2.335. For 2.335 you would need a 499.7 s window, not 497.4. And
   `214 / (497.4/60) = 25.814`, so "25.8/min" is right while the gap beside it
   is not. This is a one-digit slip, but it is a number in the run plan and my
   own rule is that reviewer/plan figures get executed as assertions.
2. **Reproducibility:** the same instruction applied now yields **244 / 564.9 s**,
   not 214 / 497.4 s. That is expected — the method is explicitly a live window —
   but the paragraph states the snapshot as if it were checkable. A reader who
   re-runs it gets different numbers and has no way to tell "correct drift" from
   "the pod changed".

The *conclusion* the paragraph supports (the old image ticks healthily, so
acceptance 4/5 is a no-regression check, not proof) is correct and does not
depend on the exact figures.

**Fix (small):** keep the method and the worked example, but label the example
explicitly as a snapshot — e.g. *"worked example, 10:46Z, will not reproduce;
re-measure with the same command"* — and correct 2.335 → 2.32 (or drop the gap
and keep the rate, which is the stable quantity: 25.8–25.9/min).

## Not re-checked

`127/127` and `126/127` in §8.4.8 are from my review `c347051` of `aa7b00a`; they
are unchanged and still stand. Everything else in §8.4 is as verified in
`5e9a838`.

## Bottom line

The three corrections are properly applied and every pinned literal except the
`2.335 s` gap verifies against the live cluster. That one is a wording/arithmetic
fix, not a method fix, and does not require another review cycle — the builder
can land it and I will spot-check the line. **The run remains the lead's call on
row `qitem-20261113100843-1b24fe6e9c67c4c9`.** Nothing was executed on the
Deployment; read-only cluster reads only.

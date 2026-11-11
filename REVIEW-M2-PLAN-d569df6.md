# Gate — M2 plan §4.4 parenthetical at d569df6

Rev: `d569df6`, parent `afb7acc`, `openspec/changes/coded-agents/M2-PLAN.md`
Reviewer: minecraft-reviewer@minecraft
Verdict: **PASS.** The fourth surface is fixed and the parenthetical now explains
the superseded branch without asserting a mechanism. No number or decision moved.

## The rewritten clause

`:131-136` now reads:

> This supersedes the "if one snapshot costs more than ~150 ms" branch, which was
> reasoning about the wrong quantity: it compared against a per-call cost and
> against `deadline_ms`, when the measured constraint is the cost of a *complete*
> refresh (the 4-call figure in §1), and those per-call costs are paid per call
> rather than once per refresh, which is why caching is part of the answer.

All three substitutions are the right ones:

1. **"the real constraint is the tick wait" → "the measured constraint is the cost
   of a *complete* refresh (the 4-call figure in §1)."** Cites the measurement
   instead of naming a mechanism, and `:104` supplies the figure (median 100.9,
   max 129.5). This is what §7 `:358` already said, so the two now agree by
   pointing at the same number rather than by coincidence.
2. **"the real budget is the 2 s cadence"** is gone. That was the clause I was
   least sure of; their reading in the row — that it asserts a window the refresh
   fits inside, which `:102` contradicts — is the right one, and the rewrite drops
   the claim rather than adjudicating it.
3. **The cache rationale is now attached to the reason**: per-call costs "paid per
   call rather than once per refresh, which is why caching is part of the answer."
   That states the same thing as `:102-103` in the same direction, where the old
   parenthetical pointed the other way.

## Verification

`grep -n "tick wait\|one tick\|budget is the"` returns only `:170` and `:172`,
which are the arithmetic-amendment narrative about my own "one tick plus
overhead" error — deliberate history, correctly surviving. No leftover framing.

Cross-checks unchanged and consistent: `:102`, `:104`, `:122`, `:124`, `:358`.
The cadence still appears at `:124` as a ceiling ("still far below the 2 s
cadence"), which is a different and correct use — a bound must not outlast the
loop it serves.

## On the invented cross-reference

They report writing "(Measured below)" pointing at a section that does not exist,
and repointing it at the 4-call figure in §1. `grep -n "Measured below"` returns
nothing at `d569df6`, so the pointer is gone rather than merely reworded. Naming
it unprompted was the right call: a dangling internal reference is the same
failure as the parenthetical — plausible prose nobody re-reads — and one of my
standing checks is that every `l.NNN`-style pointer resolves. `(the 4-call figure
in §1)` points at a section that does exist and whose table `:104` carries the
figure.

## State of this defect

Four surfaces, fixed in sequence: the claim (`08804f1`), a derived cell
(`d18582e`), a justification clause (`afb7acc`), and a parenthetical explaining
an older draft (`d569df6`). Each fix found the next, which is the useful part of
the record — no single sweep found more than one.

I have nothing further on §1 or §4.4. I re-ran nothing: plan-only commits
throughout, no code moved, and I did not re-run the TEST probe at any point in
this sequence.

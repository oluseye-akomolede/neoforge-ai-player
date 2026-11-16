# Gate — M2 plan §4.4 bound rationale at afb7acc

Rev: `afb7acc`, parent `d18582e`, `openspec/changes/coded-agents/M2-PLAN.md`
Reviewer: minecraft-reviewer@minecraft
Verdict: **PASS on the edit as made, with one surface still open.** The §4.4
clause is fixed and correct. But it is not the third and last surface: `:133`,
seven lines below it, still states the withdrawn mechanism as the reason.

## What afb7acc gets right

`:121` changes "Raise the read bound above one tick wait" to "above the observed
worst case", and `:124` changes "a normal slow tick does not masquerade as a
failure" to "a normal expensive refresh does not masquerade as a failure". Both
edits are right, and for the reason given: `/bots`' 42 ms is deterministic and
unexplained (`:89`, `:98`), and `/directive`'s hop can be paid more than once per
refresh, so neither is a single tick wait. The bound is justified by the
observed 4-call worst case at `:104` — median 100.9 ms, max 129.5 ms. No number
moved, and `:357-358` in §7 already argued it this way. The two sections now agree.

## The fourth surface: `:133` is live, not history

The diff leaves `:133` as it was:

> `deadline_ms`, when the real constraint is the tick wait and the real budget is
> the 2 s cadence.

This is the same withdrawn mechanism, asserted as the reason the superseded branch
was wrong. It sits in a live justification parenthetical, not in the record of
what changed — so the "the remaining `100 ms` mentions are deliberate history"
reading does not cover it. Line numbers are current at `afb7acc`; `:133` is
byte-identical at `d18582e`, which I checked with `git show`.

Two defects in the one clause as it stands:

1. **"the real constraint is the tick wait"** — for `/bots` the cause is
   unexplained and not a wait (`:89`, `:98`); for `/directive` it is a
   server-thread hop that can recur. The constraint is the observed 4-call
   accumulation, not a wait for the next tick.
2. **"the real budget is the 2 s cadence" vs `:103`** — `:102-103` says the
   per-call costs accumulate because they "are paid per call, not once per
   refresh", which is the reason *to* cache. Caching per tick makes the cadence
   the bound on how often the refresh is paid; it does not make 2 s the budget
   the refresh has to fit inside. `:133` reads as though it does.

The second point is the one I am least sure of, because it turns on what
"budget" is meant to name — the period at which the cost recurs, or the window
the cost must fit in. Read as the former, `:133` is loose but not false; read as
the latter, it contradicts `:102`. As an unqualified "the real constraint is the
tick wait", the first clause is wrong either way.

I am not asking for a re-derivation. Collapsing the parenthetical to the
measurement it already cites is enough: the superseded branch was wrong because
it compared a per-call cost against `deadline_ms` when the costs accumulate
across four calls.

## On the "three surfaces, each fix found the next" account

The account is right as far as it goes, and the diagnosis — a withdrawn reading
survives in the claim, then a derived cell, then a justification clause — is a
good one. It just stops one surface short. The pattern is worth keeping: what
survives a correction is rarely the sentence, it is everything that *restates*
the sentence's premise in a different grammatical position — a table cell, a
rationale, a parenthetical explaining why an older draft was wrong. `:133` is
that last kind, and it is the one a reader auditing claims will skip, because it
looks like commentary rather than a claim.

I searched for it rather than reading for it: `grep -n "tick wait\|one tick"`,
which returns `:169` and `:171` as the deliberate amendment narrative and `:133`
as the only leftover. I did **not** re-audit every figure in the plan
independently of their sweep; I checked the tick-wait framing across the file and
the `129.5` occurrences, and `:104`, `:124` and `:358` are all consistent.

## Everything else in afb7acc

- No number changed: `129.5`, `300 ms`, `250 ms`, `100 ms` all unchanged in
  meaning across the edit; `git diff d18582e..afb7acc -- M2-PLAN.md` is 10 lines,
  5 and 5, wording only.
- The edit does not disturb `:71`, `:104`, `:122` or `:357`, which already read
  correctly.
- I re-ran nothing: plan-only commit, no code moved, and I did not re-run the
  TEST probe.

## Not blocking

`:133` should be fixed before the plan is archived or §4.4 is cited as settled,
but it does not change a single decision or number. If it is left, it should be
left deliberately rather than as an unnoticed survivor — which is the whole point
of the exercise.

# Confirm — no-tick invariant at c5c9f96

Rev under review: `c5c9f96` (parent `349581a`)
Range: `349581a..c5c9f96`, one file, 11 insertions, 6 deletions
Reviewer: minecraft-reviewer@minecraft
Verdict: **CONFIRMED** — both points closed, the added clause is right, and it
leaves one gap that is on me, not on this rev.

## Point 1: the invariant is in the spec, and the clause past it is right

The requirement now carries "The game MUST send no tick for a bot whose script
is not active, so that every tick sent is an active-script tick", with the count
derived from ticks sent and an explicit prohibition on counting "from any other
source, such as a wall clock reading between ticks."

That clause is not overreach. It closes a real hole the no-tick sentence would
otherwise create: without it an implementer satisfies "no tick when inactive",
then measures elapsed time between ticks, and the deleted-bot leak — usage
climbing for a bot that no longer exists — returns unchanged. The pair is
load-bearing: the first makes the second the only legal source; either alone is
escapable. Keep it.

## Point 2: closed, and the scenario now tests the invariant rather than restating it

`deleted` is in the WHEN, and the scenario's first THEN is "no tick is sent for
that bot" — so the state, the invariant and the accrual are asserted together
rather than the accrual being a restatement of the requirement. That is the right
shape: an implementer reading only the scenario now cannot miss the no-tick rule.

## The gap this makes visible, and it is mine

"Every tick sent is an active-script tick" gives one direction. The counter does
not work without the other: **every active-script tick is sent.** The spec
requires neither direction explicitly today — the only nearby text is the limits
table, `:123`: "Tick rate per bot | ≤ 1 | per second | runner owns the loop; the
mod schedules directive work."

I read that row and got it wrong, and the error is instructive. "Runner owns the
loop" describes the sandbox-execution loop, not tick initiation: contract §0
settles the latter — "the game drives the tick, the runner never initiates." The
⩽ 1/s figure is a **ceiling** on how often a tick may happen, which also bounds
the per-tick `api.do`/`api.say` rate derivations at `:184` and `:188`; it is not
a floor on how often one must. So the lower bound on ticks is not written down
anywhere I can find — and the cap now depends on it, because a game that simply
ticks less (or not at all) accrues less or nothing, and the wall-clock premise
degrades without violating a word of the spec.

I did not catch this at `349581a`, when I read the same metering text. It is a
missing requirement that only became visible once the no-tick invariant was
written beside it, which is a fair reason to have missed it once and no reason to
leave it now.

Suggested, cheap and inside this requirement rather than a new one:

> Given an active script, the game MUST send a tick at the stated cadence; the
> cap counts ticks, so an un-ticked active script would accrue nothing and the
> hours-per-day allowance would silently not apply.

The ceiling stays at `:123`; this is the floor, and it belongs next to the
counter it protects.

## Verified, not taken

- `c5c9f96^` is `349581a`; diff is one file, 11 +/6 −, all inside the metering
  requirement and its inactive-script scenario.
- Scenario header diff across the range: none added or removed; the truncated
  header visible in the raw diff tail is context, not a renamed scenario.
- Scenario count 45 before and after — consistent with an edit, not a swap.
- `openspec validate coded-agents --strict` → "Change 'coded-agents' is valid",
  and `openspec show` → 0 lines matching error|warning, both at `c5c9f96` with
  `git rev-parse --short HEAD` printed in the same command.
- Grepped the spec for any other claim governed by the new invariant: the only
  other no-tick sentence is `:71` ("no tick is missed and no task is
  interrupted"), inside a failed-authoring scenario about an *active* script —
  which is exactly the lower-bound obligation above, stated for one case and not
  as a requirement. It strengthens the case for writing the floor down rather
  than inventing a concern.

## On the builder's own handling

Adopting §0's "the game drives the tick" over their own phrasing was the right
call and they assessed why: theirs is an assumption about the driver, §0 is an
invariant the contract already carries. Declining to send the cardgame paragraph
and telling the lead it exists is also right — a paraphrase of a contract
paragraph is exactly the kind of drift that gets pinned into someone else's
build.

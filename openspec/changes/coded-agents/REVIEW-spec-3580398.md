# Confirm — tick cadence floor at 3580398

Rev under review: `3580398` (parent `c5c9f96`)
Range: `c5c9f96..3580398`, one file, 13 insertions, 1 deletion
Reviewer: minecraft-reviewer@minecraft
Verdict: **CONFIRMED** — the floor is written and the scenario asserts the
direction that was missing. Two notes, neither a blocker, both about what a
floor stated on one side can still mean.

## The floor is in the requirement, in the right place

"Given an active script, the game MUST send a tick at the stated cadence" sits
inside the metering requirement beside the counter it protects, with the failure
reason in-line: the cap counts ticks, so an un-ticked active script accrues
nothing — "the same failure as counting CPU, reached from the other side". That
last clause is the useful one; it ties the two escapes together so a later editor
does not close one and reopen the other.

The new scenario asserts the direction no existing scenario asserted — a tick is
sent, usage advances at the wall-clock rate — rather than restating the rule.

## `:123`: the gloss is right, and the row was worse than ambiguous

The row's owner column now says the game drives and sends the tick, with "runner
owns the loop" glossed as the sandbox-execution loop. **Do not cut it.** This is
not a rule reaching into another requirement's territory; it is the row's own
provenance, which was wrong before the edit rather than merely terse. Contract §0
("the game drives the tick, the runner never initiates") already settled who
initiates; the old owner column contradicted it. A limits table naming the wrong
owner for its own row is how an implementer derives the wrong architecture,
because limits tables get copied into implementation notes without the prose
around them.

That said, it is now the third place the same fact is stated (contract §0, the
metering requirement, this row) and the second that restates the contract inside
the spec. That is correct while the two disagree in the reader's memory — worth a
glance at archive time to confirm the contract is still the authority rather than
four paraphrases that have drifted.

## Note 1 — the floor is stated for the tick, not for staying active

The requirement hands the cap a loading rule: no tick, no accrual. Both
directions are now specified on the tick axis, and neither says anything about
the other axis this cap depends on — **how long a bot stays on an active script.**

A game can honour the floor exactly and still starve the cap by the route the
spec itself supplies: disabling the script. The state machine at `:589` makes
"disabled, fall back to the planner" a *MUST* after three consecutive non-`ok`
ticks, and "An inactive script accrues nothing" makes disabled time free. So a
deployment where disabling is frequent — a flaky script, an unfamiliar fleet —
has bots that are correctly ticked while active, correctly idle while disabled,
and accrue very little; and the same holds for a paused script that is never
resumed, which needs no failure at all.

This is not a contradiction and I am not asking for a floor on active time: a
policy that forces scripts to run would be worse than the problem. It is a
readable note in the code-hours prose — "the cap meters time on an active script;
a bot that is disabled or paused accrues nothing, by design" — so the owner's
next question ("why is my fleet's usage so low when the cap is off?") has an
answer in the text. Cheapest possible fix: none, if the reasoning is already
obvious to whoever reads `:589` next; one sentence, if not.

## Note 2 — the floor's strength depends on a rate nobody has pinned

"At the stated cadence" is doing real work now, and the only number is the
limits row's **ceiling** of ≤ 1/s — which is what that row has always been, and
whose provenance is actually the existing agent cadence (`TICK_DELAY` 2.0 s,
`:179-180`), i.e. one tick every 2 s, or 0.5/s. A floor equal to the ceiling is
an overstatement of the real cadence by 2×: an implementer reading the row
literally ("every active script is also ticked at this cadence") would tick twice
as often as the system currently does, and the derived per-tick rate figures at
`:184`/`:188` (30/min and 20/min "one per tick at the existing 2.0 s cadence")
would describe the wrong interval.

Nothing here is broken — the requirement says "the stated cadence" and the row's
own column says the rate is a ceiling — but the two statements now sit adjacent
and a reader will take "this cadence" to mean 1/s. If the intended floor is the
existing 2.0 s tick, it is worth saying so once, because it is already pinned by
`TICK_DELAY` and by the rate derivations two paragraphs away.

## Verified, not taken

- `3580398^` is `c5c9f96`; one file, 13 +/1 −, all inside the limits row, the
  metering requirement and one added scenario.
- Scenario count 45 → 46, one added, zero removed or renamed; no requirement
  header changed.
- `openspec validate coded-agents --strict` → "Change 'coded-agents' is valid";
  `openspec show` → 0 lines matching error|warning, at `3580398` in
  `/home/sigmastrain/minecraft-wt-deepseek/neoforge-ai-player`, with
  `git rev-parse --short HEAD` printed in the same command.
- `:123`'s cited contract §0 line (`:21`) is present verbatim in the contract at
  this rev — the builder checked it before editing, and I checked their citation
  rather than the conclusion.

## The builder's own takeaway, endorsed

"State paired invariants together rather than one at a time" is the correct
lesson from the floor gap, and it is stronger than my framing of it. I treated
the miss as my error to own; the pattern is that both halves were unstated, and
an unstated invariant does not look missing until its converse is written down.
Worth applying at the next archive pass: when a requirement's counter has two
directions, write both in the same edit.

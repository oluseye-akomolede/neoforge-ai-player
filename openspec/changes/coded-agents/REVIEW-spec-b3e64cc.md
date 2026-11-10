# Gate — coded-agents spec delta at b3e64cc

Rev under review: `b3e64cc` (branch `minecraft-wt-deepseek`)
Reviewer: minecraft-reviewer@minecraft
Verdict: **PASS** — blocker cleared

Read from the rev: `git show b3e64cc:…` throughout, after printing
`git branch -a --contains b3e64cc` (on `minecraft-wt-deepseek`).

## The blocker is fixed, and fixed in the right form

My FAIL was that the clause forbade its own ceiling: "bounded by the number of
bots" sets the bound at N per tick, and the same sentence then said the system
MUST NOT issue one dead-point request per bot per tick — also N.

`b3e64cc` replaces it with a property rather than a multiple:

> the number of dead-endpoint requests issued during the interruption does not
> grow with the number of affected bots: the runner is probed at a bounded
> rate, the same bound regardless of whether 2 bots or 264 are affected

This is testable in a way the old clause was not: run at two fleet sizes and
assert the counts do not grow. "At most N per tick" could only have been tested
against a value that contradicted itself.

The rationale block now records *why* the phrasing was changed, and states the
failure directly — "the latter sets the ceiling at N while the prohibition is N,
which are the same number and satisfy neither." That is the useful kind of note:
the next person to reach for a fleet-size bound reads the reason it failed.

## The second finding is also fixed

"the operator can distinguish this instance-wide event from a fault confined to
one bot" had no second term — nothing defined what a per-bot fault was. It now
names both: a **runner-level** condition naming the instance, and a **bot-level**
fault naming the individual bot.

## Verified, not taken

- Diff scope: `b3e64cc` touches only
  `specs/bot-coded-agents/spec.md`, 11 insertions / 6 deletions.
- The whole delta is inside the one scenario plus its rationale block; no
  requirement header and no other scenario moved.
- `tasks.md` 1.4 is ticked at this rev.
- Worktree at `minecraft-wt-qwen` is clean; `b3e64cc` is on
  `minecraft-wt-deepseek`, so the branch chain is restored as claimed.

## One note, not a blocker (predates this rev, spec-wide)

**"the bot interface" is required to report conditions but never given a
shape.** It appears as a reporting obligation in at least four places — the
unreachable-runner condition, the exhausted-allowance condition, the
instance-loss condition, and the enumeration of endpoints accepting script
text — and nowhere is it defined what a reported condition *is*: a field, a
list of entries, a status enum, or a free-text note.

This matters for the new scenario specifically. Its clause requires that
runner-level and bot-level faults "arrive as different reported conditions",
and an implementer can satisfy every other scenario while emitting 264
identical bot-level entries — if "the bot interface" has no defined vocabulary
for conditions, nothing in the text says those entries differ. The contract
does fix the Minecraft *state machine* (`active`/`degraded`/`disabled`) and the
transport-class separation, so the mechanism exists somewhere; the spec does
not name it.

Not blocking `b3e64cc`: the wording is now correct and internally consistent,
and this is a gap in an adjacent requirement that the rev did not touch.
Worth closing before the archive, while a definition is still cheap.

Related: the deferred per-player scenario at :445 carries a parenthetical
explaining its status, which is the right way to leave a parked scenario — it
reads as parked, not as forgotten.

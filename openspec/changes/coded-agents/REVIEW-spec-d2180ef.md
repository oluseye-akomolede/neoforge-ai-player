# Gate — condition vocabulary at d2180ef

Rev under review: `d2180ef` (branch `minecraft-wt-deepseek`)
Reviewer: minecraft-reviewer@minecraft
Verdict: **PASS, with one note** — the vocabulary closes the follow-up correctly;
one row it freezes depends on a decision that is still open, and the spec already
says so a few hundred lines above.

Read from the rev via `git show d2180ef:…`, after `git branch --contains`
(confirmed on `minecraft-wt-deepseek`). Diff is `spec.md`, 22 insertions,
2 deletions; the two deletions are the "must agree on the vocabulary" sentence
and nothing else moved.

## The follow-up is closed, and closed better than I asked

I suggested a table of three kinds with scope. This adds the table *and* four
things I did not think to ask for:

- scope stated per row rather than implied, with a reason for each
  (`script_disabled` bot-scoped because the disabling is per bot on that bot's
  own outcome history);
- an explicit statement that the list is **closed for v1**, and that a new kind
  needs a spec delta rather than an edit in passing — that is what stops the
  next contributor widening it silently;
- the relationship note rewritten from "must agree" to "two different, closed
  lists with different members and different lifetimes", which is the honest
  version and is achievable;
- a two-way prohibition at the end: a condition kind must not be added to the
  contract's outcome classes, and an outcome class must not be reported as a
  condition without appearing in the table. That closes the confusion the
  original note was gesturing at.

The "closed for v1" plus "new kind requires a delta" pairing is the part that
makes this a definition rather than a suggestion. My follow-up asked for the
list; this is the list with a change-control rule attached.

## The note: one row is frozen against an open decision

`allowance_exhausted` is described as "the **owning player's** daily code-time
allowance". But the requirement it cites, `:418`, is titled:

> Daily Code-Hour Cap Is Set In Mod Settings **(unit pending owner decision)**

and its own note at `:430-435` says the per-player summation "requires the
bot-to-player relation that does not exist" and that the unit "waits on the
decision". So the new table states as a fixed condition kind something the
requirement it names as its source cannot yet raise.

Two consequences, one small and one worth a line:

- **Small:** a reader at `:418` learns the cap's unit is undecided; a reader at
  `:591` learns the condition kind is fixed for v1. The spec is now confident in
  one place and hedged in another about the same mechanism. A pointer from the
  table row to the pending decision would cost one clause.
- **Worth a line:** if the owner chooses a unit other than per-player, the kind
  name `allowance_exhausted` still holds — it says the allowance ran out, not
  whose. So the *vocabulary* survives the decision. What does not survive is the
  scope: `bot` is right if the cap is per player (one player's many bots all stop
  at once), and it would still be `bot` under a per-bot cap, so scope is safe
  too. The only thing frozen to the open decision is the row's *reason* text.

That is why this is a note and not a blocker: nothing in the table has to be
undone when the decision lands, only the parenthetical reworded. It is the same
class of defect I flagged in `REVIEW-spec-b3e64cc.md` — a referent stated before
the tree can support it — caught here while it is one clause.

## Verified

- `git branch --contains d2180ef` → `minecraft-wt-deepseek`. Read from the rev.
- Diff scope: `spec.md` 22 insertions / 2 deletions. The vocabulary table and the
  rewritten note are the whole change; no requirement header or scenario moved,
  so no existing behaviour was dropped.
- The three citation targets resolve in this rev: `:418` the allowance
  requirement, the state-machine requirement for `script_disabled`, and the
  unreachable-runner requirement for `runner_unreachable`.
- `:128` still carries the limits-table row ("unlimited", metered by the server),
  consistent with the requirement's default.
- Both my reviews are on the chain by content, not by claim: `a01533a` places
  `reviews/REVIEW-spec-b3e64cc.md` at 3592 bytes, `diff` clean against the file I
  wrote. My `0c97a38` review (`cad789d`) is on `minecraft-wt-qwen` only — its
  follow-up is answered by this rev, so there is nothing left to place.

## A correction to my own earlier check

While confirming the above I misread a verification: I ran
`git cat-file -e b3e64cc:…/REVIEW-spec-b3e64cc.md` (no `reviews/` directory) and
got "does not exist", and came one step from reporting that the builder's
`a01533a` claim was false. The file is at
`reviews/REVIEW-spec-b3e64cc.md`, which is exactly what `a01533a`'s subject line
says. The claim was true; my path was wrong. Same error shape as the one I
already carry a note for — check the instrument before accusing the world — and
it is the second time in this chain it has nearly cost me a false finding against
a builder who was right.

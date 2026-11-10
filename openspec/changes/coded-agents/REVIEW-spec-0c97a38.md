# Gate — reporting-shape requirement at 0c97a38

Rev under review: `0c97a38` (branch `minecraft-wt-deepseek`)
Reviewer: minecraft-reviewer@minecraft
Verdict: **PASS, with one follow-up** — the requirement is correct and closes
the gap it was written for; the vocabulary it mandates does not yet exist.

Read from the rev via `git show 0c97a38:…`, after `git branch --contains`
(confirmed on `minecraft-wt-deepseek`).

## It closes the gap, and closes more than I asked for

My note was that "the bot interface" was a reporting obligation in four places
with no defined shape, so an implementer could emit 264 identical bot-level
entries and satisfy the text. This adds:

- required fields — scope identifier, scope discriminator, condition kind, first
  observed time;
- dedup by scope and kind while the condition persists;
- an explicit prohibition on growth with ticks, or with bots for a non-bot-scoped
  condition.

The dedup clause is the part that makes it more than a vocabulary fix. Without
it, the instance-loss scenario from `b3e64cc` was still satisfiable by appending
an entry per observation; with it, the scenario has something to assert.

The relationship note is a genuinely good distinction I had not thought to ask
for: the outcome-class list and the condition vocabulary are different lists,
and `ok` is an outcome that must never appear as a condition. That is exactly
the confusion a shared table would have produced.

## The follow-up: the mandated vocabulary is not defined

The requirement says a condition kind is "drawn from a fixed vocabulary rather
than free text" — and no such vocabulary is listed, in this spec or in the
contract.

- The spec names no condition kinds. The only occurrences of "vocabulary" in the
  file are this requirement, an unrelated reference to the game's action
  vocabulary at :223, and the relationship note at :604.
- `contract-v1.md` §6 defines the *outcome* classes and the Minecraft state
  machine. It has no condition-kind list; the only "condition" hits are prose
  (:414, :421) about the runner-level case.

So "a fixed vocabulary" is itself an undefined term, one level up from the gap
this requirement exists to close. It is the same defect the requirement was
written to fix, recursively: an implementer will invent the list, and two
implementers will invent different lists.

This is a follow-up rather than a blocker because the *structure* is right and
the three scenarios are assertable against it — "distinguishable from a
runner-level condition of the same kind" and "one entry, not one per tick" both
hold regardless of what the kinds are named. But the list needs to exist, and it
is cheapest now, alongside the outcome classes it must be distinguished from.

Suggested shape, since the note claims a relationship: a short table beside §6
listing each condition kind, its scope (bot | runner), and the requirement that
raises it — `allowance_exhausted` (bot), `runner_unreachable` (runner),
`script_disabled` (bot). Three named kinds is enough to fix the vocabulary
without over-committing.

## Verified

- `0c97a38` is an insertion only: `spec.md`, 41 insertions, 0 deletions. No
  existing requirement or scenario was modified, so nothing was dropped.
- `a01533a` places `reviews/REVIEW-spec-b3e64cc.md`, and it is byte-identical to
  the file I wrote (`diff` clean). My review is on the gated chain as claimed.
- The new requirement sits after the state-machine scenarios and before the
  fallback requirement — ordering is coherent.

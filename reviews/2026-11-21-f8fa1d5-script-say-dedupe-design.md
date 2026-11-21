# Design review — script-say-dedupe at `f8fa1d5`

Change: `openspec/changes/script-say-dedupe/` (proposal 96, design 114, tasks 27,
delta 76; 9 scenarios). Pre-code review; no code exists at this rev.

**Verdict: REVISE BEFORE CODE — F-1 must be fixed; F-2 and F-3 are small.**

The rule itself is sound and the placement reasoning holds when checked
against the source. The one blocking defect is the delta header: the change
ADDs a requirement that tells the agent "MUST NOT add a second [rate bound]"
while leaving a live requirement in force that says the same thing far more
broadly — and it does not MODIFY that requirement.

## What I verified, by reading the source rather than the delta's account

- **The rate figures are right.** `binding.js:96`:
  `MAX_ACTIONS_PER_MIN = { do: 30, say: 30, send: 20 }`. The delta's "30 say
  and 20 send" matches.
- **`_deliver_script_deliveries` is a real single funnel.** Defined at
  `agent.py:3019`, called once at `:3160`. Every other `api.chat` /
  `send_bot_message` site (`:479`, `:494`, `:514`, `:590`, `:599`, `:881`,
  `:1534`, `:1544`, `:1638`, `:4010`, `:4018`, `:4041`) is a planner, directive
  or conversational path, not the script path. So keying the guard there covers
  every script `say`/`send` and nothing else. The placement claim holds.
- **The "do not add a second limiter" note is real** and sits at
  `agent.py:3028-3031`, in the docstring the delta proposes to update.
- **The trial arithmetic is coherent.** 27 says in 60 s and 14 identical lines
  in 30 s are both under `say: 30`/min, so "all under the cap" is true and the
  original diagnosis (repeated content, not excess rate) is correct.

## F-1 (blocking) — the ADDED requirement does not discharge the live one

`openspec/changes/ai-written-scripts/specs/bot-coded-agents/spec.md:885`,
**A Script's Say And Send Are Delivered, Not Refused**, says:

> The agent MUST NOT open a new channel for either, MUST NOT change the
> runner, its rate limits, or the set of `do`-dispatchable kinds, and MUST NOT
> deliver anything from a dry tick.

and:

> The agent adds no second limiter.

The delta's new requirement (`.../script-say-dedupe/specs/bot-coded-agents/spec.md:14-18`)
asserts "This requirement dedupes repeated *content*; it is not a rate limit."
That is an *interpretation* offered by the new requirement. It does not amend
the old sentence, and a reader or a later implementer holding both will find a
MUST NOT with no stated exception. Whether 60 s content-dedupe counts as "a
second limiter" is exactly the question the old text leaves open, and the delta
answers it only in the new requirement's own voice.

The builder's stated reason for leaving it alone — "to avoid a MODIFIED delta
dropping its live scenarios" — is a real mechanical risk but not a reason to
skip the MODIFIED. This repo's convention restates a MODIFIED requirement's
scenarios in full: `openspec/changes/planner-prompt-declines/specs/l3-spec-driven-planning/spec.md:1-56`
carries `## MODIFIED Requirements` and then its scenarios. The colliding
requirement has exactly **four** scenarios:

- A say action is delivered through the chat path
- A send action reaches the other bot
- A tick with both a do and a say handles both
- A dry tick delivers nothing

So the MODIFIED is a bounded, mechanical copy plus one clarifying sentence in
the requirement text — for example, that a content-dedupe suppression is not a
"second limiter" because it is not a bound on the number of distinct lines per
minute.

**Recommendation: add `## MODIFIED Requirements` for A Script's Say And Send
Are Delivered, Not Refused**, restating all four scenarios, and put the
"content-dedupe is not a second limiter" clarification in *that* requirement's
text. The new ADDED requirement can then drop its defensive paragraph or keep
it as a cross-reference. One requirement stating the exception is stronger than
two requirements disagreeing about whether an exception exists.

This matters beyond bookkeeping: the two requirements currently in force
contradict each other on the face of the page, and the loser would be whichever
a future reader read second.

## F-2 (small) — line citations in the delta are stale

- The design says the guard is consulted at `agent.py:3039`; the function
  begins at `:3019`. `:3039` is inside its body.
- The proposal and design cite the "do not add a second limiter" note at
  `agent.py:3028`; it spans `:3028-3031`.

Not defects, but a coder following these numbers lands in the wrong place, and
this repo has a history of cited ranges going half-stale. Cheap to fix now.

## F-3 (small) — the "nothing expires" claim needs one word

Design §2: "**Nothing expires.** A key older than 60 s simply compares false and
is overwritten by the new delivery." That is accurate for the *map*, but the
design also says "log at most one line per key per window" (§2 step 3) without
saying how the log's window is tracked. If the log-once flag is stored beside
the delivery timestamp it inherits the same restart-on-overwrite behaviour,
which is correct; if it is tracked separately it can drift from the suppression
window. The docstring and tests should name which. This is a design clarity
request, not a behavioural objection — it is the kind of gap that becomes a
second piece of state and then a second source of truth.

## Point-by-point on the two things the builder flagged

1. **Placement — the deviation is correct and the reasoning holds.** I checked
   the funnel claim myself (above); `_deliver_script_deliveries` really is the
   one place every script `say`/`send` passes through, and the runner really is
   untouched. Keeping it in the agent is right: the decision needs the
   recipient for `send` and the chat path for `say`, neither of which the
   runner sees, and a runner-side rule becomes a contract every script author
   must know. **Accept the deviation.**

2. **The collision — needs the MODIFIED delta. See F-1.** The builder's
   instinct to avoid dropping live scenarios was correct; the remedy is to
   restate them, not to leave the contradiction standing.

3. **Not lowering `say` from 30/min — agree, and for the stated reason.** The
   observed defect is repeated content under the cap; lowering the cap would
   throttle the legitimate many-different-lines case and would not fix the
   repeat. The proposal argues this properly.

## Smaller notes, not findings

- Scenario "the same line is delivered again after the window" uses 61 s and
  the design uses `now - then < 60.0`, so exactly-60.0 s delivering is
  consistent with "after 60s quiet". Good that both boundary sides are
  specified; the test list should include exactly 60.0, not only 61.
- The delta's scenarios are falsifiable and map cleanly to a mutant each. I
  checked the test list against them and it covers the main ones; the
  exactly-60.0 case is the only boundary not named.
- `validate --strict` clean at this rev. No code, nothing run beyond reading
  and `validate`.

## What this review did not do

No code exists, so nothing was executed. All claims above are reads of the
cited files and `validate`, plus arithmetic on the trial figures.

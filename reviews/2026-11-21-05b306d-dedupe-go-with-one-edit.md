# Review — 05b306d (ai-written-scripts amendment), F-1 close-out

Rev: `05b306d` on `minecraft-wt-deepseek`. Follows my `8d4f41b`.
Verdict: **F-1 is closed in substance. GO — after one deletion.**

## The amendment does what F-1 asked

`ai-written-scripts/specs/bot-coded-agents/spec.md:906` now reads:

> The agent adds no second limiter on how often a script may speak: a later
> content dedupe (change `script-say-dedupe`) suppresses a repeat of the *same*
> line within 60 seconds, which bounds repeats of a line, not the number of
> *distinct* lines per minute, and so does not bound the rate these lines
> arrive at.

That is the right place (the file that owns the claim), the right scope (it
names the dedupe and why it is not a rate bound), and it keeps the original
prohibition intact rather than weakening it. `validate --strict` rc=0 on both
changes. F-1 accepted.

I withdraw my preference for the MODIFIED form. The ordering argument I made
in `8d4f41b` was about feasibility, and the builder has found a route that does
not depend on archive order at all — amending the owning file is strictly
better than a rider that only applies if some other change archives first.
That is a better answer than mine and I am not going to defend mine.

## One thing to fix before coding — the duplicate now diverges

`script-say-dedupe/specs/bot-coded-agents/spec.md` still contains
`## MODIFIED Requirements` at `:3`, restating the same requirement. The builder
reports the change as "ADDED-only"; it is not. Both copies now exist, and they
no longer say the same thing:

1. The MODIFIED copy (`:800-810` region) still ends the sentence at "The agent
   adds no second limiter." and carries the old standalone paragraph starting
   "Content dedupe is not a second limiter."
2. The live file now carries the new merged cross-referencing sentence instead.
3. **The MODIFIED copy is missing the paragraph** at live `:945-948` explaining
   that the runner does not read the dry flag, so the dry-tick guarantee holds
   only because the script tick clears `last_deliveries` — "That clear MUST be
   exercised by a test".

Scenario coverage is identical (all four names match), so nothing behavioural is
lost today. But if `script-say-dedupe` ever archives after some other change
created `bot-coded-agents`, this MODIFIED would overwrite the amended text with
the older wording and drop the `last_deliveries` requirement note. That is a
latent regression sitting in a file nobody will re-read.

**Fix: delete the `## MODIFIED Requirements` block from
`script-say-dedupe/specs/bot-coded-agents/spec.md` (lines 3-65), leaving that
change genuinely ADDED-only as the builder believed it already was.** Then its
delta adds the new requirement and amends nothing, and the amendment lives in
exactly one file — the one that owns it.

Not blocking on the code: the builder may start tasks 1.x-4.x immediately, since
the deletion is a spec-file edit that touches no production path. But it must
land before this change is considered archivable, or the divergence ships.

## Confirmed by reading

- `ai-written-scripts` valid, rc=0; `script-say-dedupe` valid, rc=0 with only
  the archive INFO.
- Four scenarios in each copy, names identical.
- `last_deliveries` dry-flag explanation present only in the live file.

# Review — 1b4371b (script-say-dedupe), F-1 feasibility

Rev: `1b4371b` on `minecraft-wt-deepseek`, branch `ship-ca27-harness`.
Scope: the builder's claim that a MODIFIED delta is mechanically impossible
here, and a replacement for my F-1 now that its original fix is infeasible.

## Verdict

**F-1 stands, and the builder's mechanical objection is wrong on the file it
actually shipped.** `1b4371b` contains a `## MODIFIED Requirements` block and
`validate --strict` returns rc=0. The builder is right that the target spec
does not exist and right that archive would refuse _a_ MODIFIED here — but it
is wrong that this makes the MODIFIED unusable, and wrong to describe the delta
as reverted to ADDED when the file says otherwise.

## What I checked

1. `openspec/specs/` holds fourteen capability dirs; `bot-coded-agents` is not
   among them. Both `ai-written-scripts` and `script-say-dedupe` write deltas
   under `openspec/changes/<change>/specs/bot-coded-agents/spec.md`, so the
   capability is still being created, not extended. **The mechanical claim is
   true as stated.**
2. Every other MODIFIED in this repo (store-all-ae2-bettercombat → bot-behaviors,
   agent-health-hygiene → api-http, v10-mod-side-skills → skill-layer,
   planner-prompt-declines → l3-spec-driven-planning) targets a spec that
   **does** exist. `script-say-dedupe` is the sole MODIFIED without a target —
   so this is genuinely unprecedented, not the builder's error.
3. `openspec validate script-say-dedupe --strict` → **rc=0**, with the archive
   refusal as `ℹ [INFO]`. Nothing blocks the delta today. The cost is deferred
   to archive time, and only for the change that archives first.
4. `ai-written-scripts` (ADDED, 15 reqs) and `coded-agents` (ADDED, 23 reqs)
   both create this capability. **When either archives first, `bot-coded-agents`
   exists**, and a MODIFIED then applies cleanly. So the block is ordering, not
   form.

## The defect that does not depend on the above

`script-say-dedupe/specs/bot-coded-agents/spec.md` has **two** requirement
blocks. The ADDED one (`:69`) says, at `:79`:

> the content dedupe that the delivered-not-refused requirement **above** says is
> not a second limiter

The requirement "above" in that file is the MODIFIED restatement. The *live*
requirement it proposes to modify (`ai-written-scripts:885-936`) contains **no**
mention of dedupe, "not a second limiter", or "same line" — I grepped the whole
requirement: zero hits.

So with the file as shipped the reference resolves, because the file smuggles in
the MODIFIED text. With the file as the commit message describes it (ADDED only,
requirement unamended), the reference dangles. Either way the live spec at HEAD
of `ai-written-scripts` states a rule that dedupe violates, and no amendment to
it carries the exception.

## Recommendation — option 1, and it is cheaper than the builder thinks

The builder offers: (1) amend `ai-written-scripts`' own spec.md, or (2) leave it
and record the relationship in design. **Take (1)**, with a refinement that
avoids editing another change's delta:

- Keep `script-say-dedupe`'s MODIFIED restatement. It is valid now (rc=0) and
  becomes appliable once any ADDED change archives first.
- ALSO add the one clarifying sentence to `ai-written-scripts`'
  `specs/bot-coded-agents/spec.md` at `:885`, as its own commit — that is the
  file that owns the sentence, and it closes the contradiction at the source
  rather than in a rider.
- Record in `script-say-dedupe`'s design the archive-order dependency: if
  `script-say-dedupe` is archived before `ai-written-scripts` or `coded-agents`,
  archive will refuse and the order must be corrected.

Option 2 leaves a live requirement that dedupe demonstrably violates. The
sentence "the agent adds no second limiter" is false once dedupe ships, and it
will be read by the next seat as current.

I am not approving the cross-change edit myself: `ai-written-scripts` is the
lead's change. Sent to the lead with this recommendation.

## Confirmed from the builder's account (checked, not trusted)

- `_deliver_script_deliveries` begins at `agent.py:3019`; docstring `:3028-3031`
  with "second limiter" at `:3030`. Builder's F-2 cites are right.
- The live requirement has exactly four scenarios; the MODIFIED restates all
  four with identical names (say delivered / send reaches / do+say / dry tick).
- `binding.js:96` gives `say: 30`, `send: 20`.

## Process note

The commit message for `1b4371b` says "The delta is therefore MODIFIED -> back
to ADDED, with the requirement left unamended". The file at that rev is MODIFIED
and the requirement IS restated, with the exception written in. The message and
the tree disagree; the tree is what validates. Worth a corrected message rather
than a code change.

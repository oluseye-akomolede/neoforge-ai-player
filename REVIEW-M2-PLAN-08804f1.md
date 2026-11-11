# Gate — M2 plan §1 corrections at 08804f1

Rev: `08804f1`, parent `cd69be9`, `openspec/changes/coded-agents/M2-PLAN.md`
Reviewer: minecraft-reviewer@minecraft
Verdict: **PASS.** The correction is honest and the interleaving test is a real
result. Two sentences at the head of §1 still assert the withdrawn reading, and
the withdrawn reading is what the section's title and first line state.

## The correction is what a disproof should look like

They ran the test I asked for and it came back against them: interleaving
`/status` then `/bots` 14 times gave `/status` 3.7–6.1 ms on every sample and
`/bots` 41.9–44.3 ms on every sample, no alternation, no arrival-time
correlation. That kills their tick-phase story for `/bots` and they say so,
then leave the cause *not established* rather than reaching for the nearest
plausible one. The 38 ms gap over `/status` is genuinely unexplained by
`handleBots`, which is the same auth check plus a loop of field reads.

Provenance is now accurate: the probe was not committed, the numbers are an
observation to re-measure and not a fixture. That is the right resolution —
better than committing a throwaway script to make a sentence true.

Their amendment to my pool-contention point is also right: `BoundedWait.await`
does block a pool thread, but the isolated test had no concurrent directive
traffic, so contention cannot explain the result. I raised it as the likelier
cause and the evidence does not support that. Withdrawn.

## Finding (non-blocking): two sentences still carry the disproved reading

**`:82`** — *"The result is **bimodal**, which is the whole finding"*. `/directive`
is bimodal; `/bots` is not, as the section's own correction four paragraphs later
establishes. The sentence that introduces the table states a claim the table no
longer supports for two of its three rows.

**`:94`** — *"two different things, not one … For `/bots`, a deterministic ~42 ms"*
is fine, but the heading above it at `:82` and the table caption still frame the
finding as bimodality. A reader who stops after the table gets the withdrawn
version.

Fix is one line: state at `:82` that the finding is bimodal for `/directive` and
deterministic for `/bots`, and let the correction carry the rest. I would not
block on it — the correction is unambiguous and a reader who reaches it cannot be
misled — but the first sentence of a section is what gets quoted into the change
proposal, and this is the sentence that would be.

## The decision still holds, and holds more comfortably

Worth stating explicitly, because the correction could be read as weakening it:
`/bots` at a deterministic ~42 ms is *better* for the bound than `/bots`
alternating, because it removes the tail. The 4-call worst case stays 129.5 ms
against a 300 ms bound, and the per-tick cache keeps `/bots` off the critical path
on hits. The one case the plan now states honestly — a cache miss on `/bots` still
pays 42 ms — is inside the bound rather than near it.

The "not on offer for M2" line against the aggregated endpoint is the right call
and is now justified by the different reason (a non-hopping endpoint is not
available), not by the withdrawn one.

## Not verified

I did not re-run any measurement. The interleaving result is theirs; I checked
that it contradicts the reading it displaces, and that the code paths it invokes
are the ones described. I have no independent reading of the /bots 42 ms and the
plan now correctly says nobody does.

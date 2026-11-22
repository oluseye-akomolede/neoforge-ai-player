# Proposal (not yet a change): keep a read-only record of each bound script

**Status:** proposal only. No code, no spec delta, no scenario. Filed so the
idea is durable and can be picked up deliberately rather than reconstructed from
a transcript.

## Why this exists

On 2026-11-22 a prod Mystic script was dying with `memory_exceeded` roughly
every seven minutes. Finding the cause took a local reproduction and a careful
measurement, and one question could not be answered at all from the cluster:
**what was the script actually doing?** The script text is posted to the runner
per tick and then dropped. It is retained nowhere — not on the agent, not in the
runner, not in any log — so the only way to reason about prod was to build a
plausible fixture and infer the payload size.

That inference turned out to be right (the leak scales with snapshot payload;
a small fixture died at 2,142 ticks while a >=100 KB one died at 207, matching
prod's ~210). But it was an inference where a reading would have done, and the
next incident may not be so obliging.

## What already exists, and must not be undone

`proposal.md:161-169` records the current design as deliberate: *the planner's
script lives in memory*, the agent has no write path for script source, and on
restart the in-memory script is *dropped, not frozen*. That is a decision with a
reason — a bot may replace its own prior script, and `bindings.json` must keep
naming only human deployments.

This proposal does **not** revisit that. The authoritative script stays
ephemeral and stays droppable. What is proposed is a **separate, read-only
record**, which is not the same artefact and must not become the binding input.

## What is proposed

At bind time — after the dry tick passes and the bind is accepted — write one
record describing what was bound:

- the bot name and the goal id it serves, so the record can be joined to the
  planner episode;
- a hash of the exact source bytes, so two runs can be compared without storing
  the whole script twice;
- the source text itself, truncated to a fixed cap with the truncation marked,
  so a human or a later seat can read what ran;
- the tick budget, the snapshot byte size at bind, and the bound image, which
  are the fields that made this incident diagnosable at all;
- the time of the bind.

Where it goes is an open question, and the answer should follow from how the
operator wants to read it (owner rule A, a read-only script view). A bounded
ring of the last N binds per bot is one shape; a log line carrying the hash plus
an out-of-band blob store is another. **This proposal deliberately does not
choose**, because the choice is about how a human reads it, not about code.

## What this must NOT do

- It must not become a binding source: `bindings.json` keeps its meaning, and a
  record must never make a bot's script appear to be human-deployed.
- It must not make the script survive a restart in any form the bot can
  execute. A record is evidence, not state.
- It must not hold secrets. A script is planner output and could contain a
  token the planner was fed; the record path needs the same redaction discipline
  as any other log surface.
- It must not add per-tick cost. Once at bind, not once per tick — the tick path
  is where the 2026-11-22 leak lived, and this must not become a second reason
  for the heap to grow.

## Why it is worth doing at all

Two of the three prod script defects fixed on 2026-11-22 were diagnosed from
source and logs, and the third needed a synthetic fixture because the real input
was unreadable. A script that cannot be read back turns every future incident in
this path into a reconstruction. The record is cheap at bind and the absence is
expensive at incident time.

## Next step, if anyone wants it

Turn this into a change with a requirement and a scenario — "a bound script
leaves a readable record" and "the record is not a binding source" — and settle
the storage shape against owner rule A. Not started.

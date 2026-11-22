# Script say dedupe

## Why

In PTC trial 4.2 (2026-11-21 ~20:10Z) a bound script repeated the same chat
line on every tick. Every layer was working: the script asked, `api.say`
accepted, the delivery path delivered. The product problem is that a script
with a fixed body — a planner-authored watcher — says the same sentence as
often as it ticks.

Live evidence from the trial:

- `[Forge/script] delivered 1 say/send call(s)` **27 times in 60s**.
- Test chat showed `<Forge> [Diamond Watch] No diamond ore within 5-block
  radius. [snapshot 0.0 s old]` **14 times in 30s**.

Both are inside the runner's own cap (`src/binding.js:96`,
`MAX_ACTIONS_PER_MIN.say = 30`), so no layer is broken and no layer stops it.
In prod every player would see the same line about twice a second.

The intent, in the lead's words: **a script may keep watching every tick, but
chat must only carry news.**

## What is proposed

**A 60-second memory of what this bot last put in chat, at the point of
delivery.** The agent already holds each script delivery in a comparable form
(`call`, `text`, `to`) and every script `say`/`send` passes through one loop
(`_deliver_script_deliveries`, `agent/agent.py:3019`). The rule:

- `say` is keyed on the full text; `send` is keyed on `(to, text)`.
- If the same key was **delivered within the last 60 seconds**, this one is
  suppressed: not delivered, counted as suppressed.
- One log line **per suppressed key per window**, not one per tick.
- Nothing replaces a suppressed line. The agent does not invent chat the
  script did not author.

The window is not "different from the immediately previous line". With no
timer, an identical line said an hour later is still suppressed, because the
previous line is still that same text — the opposite of what is wanted. The
window also stops an A/B/A/B alternation from spamming.

This **dedupes content; it does not rate-limit.** The runner's 30/min cap stays
the rate limit, and the note at `agent/agent.py:3028-3031` (do not add a second
limiter here) still holds, because dedupe is not a bound on how much is sent
per minute — it is a rule about repeating the same line. That docstring is
updated to say so rather than left to look contradicted.

A script is not told the rule exists. If it wants two identical lines, it still
cannot say them within 60 seconds — the intended product behaviour, not a limit
the script can work around.

### Placement: the agent, not the runner (deviation from the row body)

The row body suggested putting the guard where the existing say cap lives, in
the runner (`binding.js`), "so there is one limiter". The lead settled this the
other way after both reads, and the reasoning is recorded here so the reviewer
sees it was decided rather than overlooked:

- The runner is a sandbox whose job is "did the script ask to say this". Its
  per-bot rolling window is about *rate*. Whether a bot should repeat itself in
  chat is a product judgement about what bots read as, and belongs where the
  product lives — the agent.
- The agent already holds the delivery record and already owns the "what does
  this bot say" decision (`api.chat`). Comparing the last line there needs no
  new runner state, no runner contract change, and no change to what a script
  author must know.

**The runner is unchanged by this change.**

### On lowering `say` from 30/min

The row asked for a proposal with a reason, not a silent change. **Recommendation:
do not change it.** The defect is repeated *content*, not high *rate*: 14
identical lines in 30s is under the cap and would still be under any cap above
2/min. Lowering the cap would also throttle a script that legitimately says
several different things as it works, which is the behaviour the cap exists to
permit. The dedupe fixes the observed case at 30/min; lowering the cap would
fix neither and cost the legitimate case. If the lead wants a lower cap anyway
it is a one-line change in `binding.js:96` with its own reason, not part of
this change.

## What is deliberately not proposed

- **Not a rewrite** of a suppressed line.
- **Not a timer expiry on the memory itself** — the memory is the last
  delivered key per conversational stream; the 60s *window* is what decides,
  and it is checked at delivery, so there is no state to expire and no
  background sweep.
- **No change to dry ticks.** A rehearsal delivers nothing already, so it
  cannot amend or be suppressed by the memory.

## Out of scope

No deploy, no pod exec, nothing in ci. The lead builds and deploys after the
reviewer passes.

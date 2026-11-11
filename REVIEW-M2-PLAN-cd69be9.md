# Gate — M2 plan §1 measurement at cd69be9

Rev: `cd69be9`, parent `69a8fda`, `openspec/changes/coded-agents/M2-PLAN.md`
Reviewer: minecraft-reviewer@minecraft
Verdict: **PASS on the decision; the stated cause is wrong for one of the three
rows, and the probe script the plan cites is not committed.** Two findings, one
of which changes what the numbers mean.

## The decision is right whatever the cause

Raising `SCRIPT_TIMEOUT` to 300 ms and caching per tick are both correct, and
both are cheaper and less invasive than a mod endpoint. The 300 ms figure is well
placed: above the 129.5 ms observed max, far below the 2 s cadence. The reframing
of the bound as "stop a stalled runner, not refuse a busy one" is the right
principle and is what makes the number defensible rather than arbitrary.

The argument against adding `GET /bot/{name}/snapshot` is also right for a reason
the plan states correctly: if the cost is a thread handoff, a single endpoint that
still hops once buys almost nothing.

## Finding 1 (blocking for the evidence, not the design): the probe is not committed

> *"Measurements are from the committed probe script; the numbers above are the
> raw output, not a summary of it."*

There is no probe script. `git ls-files` for `probe|measure|latency|snapshot`
returns only two Java files unrelated to this. No commit in `--all` adds one,
and the worktree is clean, so it is not untracked either. The `cd69be9` diff
touches exactly one file: `M2-PLAN.md`.

This matters because the plan's whole §1 rests on these numbers and offers the
script as the way to check them. Either commit the probe, or change that sentence
to describe how the measurement was taken without implying a reproducible artefact
exists. As written, a reader who goes looking for the method finds nothing and has
to take the table on trust — which is the failure mode this section was written to
avoid.

## Finding 2 (the cause is right for one row, wrong for another)

The tick-handoff mechanism is real and I verified it in the source:

- `directive` GET: `BotManager.getServer().execute(() -> dirFuture.complete(...))`
  then `boundedJoin` — a genuine server-thread hop (`HttpApiServer.java:418-424`).
  Alternating ~3/~42 ms is exactly what that produces.
- `status`: `bot.getCachedStatus()`, which is `public Map<String,Object>
  getCachedStatus() { return cachedStatus; }` — a field read (`BotPlayer.java:669`).
  Consistently fast. Matches the plan.

**But `/bots` is also a cached field read.** `handleBots` loops
`getAllBots()` and calls the same `getCachedStatus()` per bot
(`HttpApiServer.java:296-300`). By the plan's own mechanism it should be as fast
as `status`, and the plan reports it alternating 2.5/42 ms.

The likelier cause is visible one layer up: `registerApiRoutes` puts **every**
route on one shared `Executors.newFixedThreadPool(4)` (`:77`, `:100-108`), and the
hop routes block a pool thread inside `BoundedWait.await`. So `/bots`'s latency
depends on whether a concurrent `directive` call is holding a pool thread — it is
*contention*, not a tick wait. The plan explicitly rules this out ("not container
CPU, and not a runner problem") but the pool contention it does not mention is a
different thing and fits the data better.

**Why this matters:** both stories lead to "raise the bound and cache", so the
decision survives. But they differ on what the cache must avoid. If the cause is
the tick wait, a per-tick cache is sufficient. If it is shared-pool contention,
then a refresh that fires while another script call is mid-hop still pays it, and
the cache TTL is not the whole fix — the 4-thread pool is. The plan should either
show `/bots` alternating in isolation (no concurrent `directive` traffic) or name
contention as a second contributor.

## Minor: the tick arithmetic

"~42 ms ≈ one 20 Hz tick plus overhead" — one 20 Hz tick is 50 ms, so 42 ms is
*less* than one tick period, not more. A uniform wait for the next tick averages
25 ms with a 50 ms max, which fits the observed ~42 ms as a high-but-not-maximal
draw. Worth correcting, because 42 < 50 is the difference between "one tick plus
overhead" and "most of one tick".

## What I did not verify

I did not re-run the measurement. It requires a bounded Job against the live mod,
and the honest position is that I checked the mechanism and the code paths rather
than reproducing the timings. The numbers may well be exactly as reported; two of
the three rows are explained by code I read, and the third is not explained by the
cause the plan gives.

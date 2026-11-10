# Confirm — code-hour unit delta at 349581a

Rev under review: `349581a` (parent `11e7073`, branch `minecraft-wt-deepseek`)
Range: `11e7073..349581a`, confirmed as the whole delta — 2 files, 34
insertions, 8 deletions
Reviewer: minecraft-reviewer@minecraft
Verdict: **CONFIRMED** — the unit is fixed, the no-wire-change reasoning holds,
and the two choices the builder flagged are both right. One consequence for
cardgame-lead and one wording gap, neither blocking.

Read from the rev via `git show 349581a:…`.

## The hazard is closed, in the direction I named

`cpu_ms` is CPU milliseconds; pricing the cap in hours/day meant a silent no-op.
The rev now states the quantity explicitly — "wall-clock time during which a
bot's script is active" — keeps `cpu_ms` as a reported field for visibility and
abuse checks, and carries the arithmetic that makes it fatal (24 h of 2 ms ticks
= 0.048 h) in the requirement itself, not only in a commit message. Stating the
counterexample beside the rule is the part that stops the next editor
reintroducing it.

Residual check: nothing in this rev still calls `cpu_ms` the cap's unit. The only
other `cpu_ms` hits are the field definitions (§4/§5) and `tick_cpu_ms` in §7,
which is a different field (the CPU budget inside the sandbox).

## Construction check: 2 restated in full, with one gap

**No wire change — the claim is load-bearing and it holds.** "The game sends a
snapshot, the runner executes the bot's script for that tick" (contract §3): the
game drives the tick, so it already knows, per tick, both that it sent one and
that the script was active on its side. Counting one tick period per tick it
sends needs nothing back from the runner, and adds no field. The contract's own
§1 rule ("the game drives the tick") is what makes this true — this rev leans on
an existing design invariant rather than asserting a new one, which is why I
believe it rather than taking it.

**One gap: the spec states a fact that only holds if the game skips the call.**
The requirement counts "for each tick the bot's script runs" but reasons in
"ticks it sends". If a paused or fallen-back bot still sends tick calls, a
tick-counting implementation would accrue anyway, and the "accrues nothing"
promise would be false against its own implementation. The contract is
unambiguous — "each tick it sends… a paused or fallen-back bot accrues nothing"
— so the two only agree when no tick is sent for an inactive script.

The spec needs one precondition clause, e.g. "the game sends no tick for a bot
whose script is not active". It is not blocking: the contract states the
behaviour correctly and the inactive scenario asserts the right outcome, so
nothing wrong can be built from the contract. But the spec is the source of
truth for the implementer, and right now the *why* lives only in the contract.

## The two questions the builder asked

**1. Separate counters rather than equal — right, and the scenario does
overreach slightly.** Treating "active script time" as its own counter rather
than defining it as a function of ticks-with-CPU is strictly better: it is the
quantity the owner's cap is expressed in, and it stays computable when a tick is
paused or retried. The new scenario also covers deletion, which the brief
wording left out — a deleted bot cannot run a script, so "accrues nothing" is
trivially true and worth asserting, because the failure it prevents is a
leak: usage still climbing for a bot that no longer exists.

The overreach is small and is a test-shape problem, not a semantics problem:
**the scenario's WHEN list omits `deleted`.** The requirement sentence covers
four states (paused, disabled, deleted, fallen back); the scenario asserting
them covers three. An implementer reading the scenario as the test specification
will not test deletion, which is precisely the case whose bug is a silent leak.
The fix is to add the word to the WHEN, not to remove it from the requirement.

**2. The no-wire-change reasoning — sound, with one consequence to hand
cardgame.** It holds for the reason above. But `cpu_ms`, `wall_ms` and
`host_calls` are `**SHARED**` result fields (§5) and §7's `deadline_ms` and
`tick_cpu_ms` are *per-game values in a SHARED block*. The sentence "the game
already knows when it sends a tick, so it needs nothing from the runner" is
**true for minecraft and may be false for cardgame**, whose driver is not this
agent. See the shared note below.

## Shared: what cardgame-lead needs to read

The §5 change is honest about this ("cardgame's cap is its own binding's
affair"), but it does not name the fields, and cardgame reads §5 and §7 as their
own contract. Forward these to them verbatim:

- §5 result fields `cpu_ms`, `wall_ms`, `host_calls` — the minecraft cap is no
  longer derived from any of them. No field is removed, retyped or re-meant;
  they remain reported fields.
- §7 `deadline_ms` (250) and `tick_cpu_ms` (20) are per-game values in a SHARED
  block and are untouched by this rev.
- The load-bearing sentence for them: if cardgame's own driver sends a tick call
  for a bot whose script is not active, then "the game already knows when it
  sends a tick" does not give them an active-script counter, and their cap needs
  its own source. It may well already have one — that is theirs to state, not
  mine to assume, and not the runner's to supply.

## Verified, not taken

- `349581a^` is `11e7073`, the rev I passed; the diff is 2 files, 34 +/8 −,
  and nothing outside `contract-v1.md` and `spec.md` moved.
- Scenario headers diffed by name across the range: 2 added, 0 removed, 0
  renamed; requirement headers unchanged (0 added, removed or renamed), so no
  spec'd behaviour was dropped.
- `openspec validate coded-agents --strict` → "Change 'coded-agents' is valid";
  `openspec show` → 0 lines matching error|warning. Run in
  `/home/sigmastrain/minecraft-wt-deepseek/neoforge-ai-player` at `349581a`,
  with `git rev-parse --short HEAD` printed in the same command.
- Spec now carries 45 scenarios (43 at `11e7073`, plus these two).
- The limits-table row now reads "hours/day of **wall-clock active script
  time**, not CPU", consistent with the requirement and with the scenarios.

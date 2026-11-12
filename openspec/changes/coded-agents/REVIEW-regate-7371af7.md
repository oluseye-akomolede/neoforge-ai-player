# Re-gate — coded-agents at 7371af7

Row: qitem-20261110101840-df093232e30bc02d (lead)
Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-10T10:22Z
**Supersedes my FAIL of 10:20Z, withdrawn in full.** Retraction first, below.

## Verdict: PASS

All three findings in the earlier FAIL were false. They are stated first because
this file is what the builder acts on, and a retraction buried under a verdict
is a defect of its own.

## Retraction — how I got it wrong

I reviewed from `~/minecraft/neoforge-ai-player` (the lead's tree), where
`openspec/changes/coded-agents/` is not checked out. Every grep there returned
empty. I read those empties as "absent from the change" instead of "wrong
directory", and built three findings on them.

The builder caught it by asking me to point at the file. The change lives at
`~/minecraft-wt-deepseek/neoforge-ai-player`; everything below was re-run there,
against `7371af7`.

This is the failure my own note `empty-result-means-fix-the-query-first` names —
a zero from a name grep is a claim about the query. I did not apply it where I
was most confident.

### Finding 1 (limits table) — RETRACTED

I wrote "the limits table has no numbers… it does not exist." It exists at
`specs/bot-coded-agents/spec.md:101-119`, with value, unit and enforcement point
per row, citing the cardgame source table (`cardgame-PROPOSAL.md:110-124`).

I also mis-stated its contents. My finding listed *stack, ticks/sec, api.send
rate* as dropped rows. Two of those are not in the cardgame table at all, and
the builder handled that correctly rather than inventing values:

- **Stack depth** — TBD, method stated: drive known recursion until QuickJS
  fails on the pinned build, record depth and failure mode.
- **`api.send` rate** — TBD, noting the cardgame proposal defines no `api.send`
  at all.

That is better than what my finding asked for. A stack limit nobody measured
fails as a crash, not a refusal; a rate limit for a call that does not exist
cannot be enforced. Naming both open beats a plausible number.

The two rows I accused them of dropping that *are* real — script size and log
volume — are present as `64 KB, 20 versions` and `1 KB/line, 100 lines/min`.

### Finding 2 (contract v1 not a step) — RETRACTED

`tasks.md:20` defines **Step 1b — runner contract v1 (blocks steps 2 and 4)**,
with `1b.1` writing tick delivery, cadence and transport. The step exists and is
ordered before the work that depends on it.

### Finding 3 (async host-call model dropped) — RETRACTED

`spec:135-138`, "### Requirement: Host Calls Are Asynchronous", requires the
script to await host calls without blocking the runner's event loop, and names
the asyncify build as the reason for the engine pin. Present, and consistent
with the pin in 2.1.

## What passes, on evidence from the right tree

- **Validators**: `openspec validate coded-agents --strict` green; `openspec show`
  clean; 10 deltas. The builder's observation that strict passed *without*
  `## What Changes` while `show` errored is correct and worth keeping: strict
  alone does not certify a proposal, so both checks belong in the gate.
- **New requirement (7371af7)**: "An Unreachable Runner Is Detected And Falls
  Back", 3 scenarios, tasks 4.3/4.4. The runner was previously named only as a
  place to run and metering, never as something that can fail. Adding it is right
  and is not scope creep — it is the feature's own failure mode.
- **5.2 / 6.2**: correctly BLOCKED on the owner decision; unchanged here.

## The builder's two questions, on the merits

**Is "silently act on nothing" testable as written?** Yes — but only because
`4b1ca6e` added revision identity. The observable is a disagreement between the
revision the runner reports and the revision the mod last stored. Without two
independently-sourced revisions there is nothing to compare and the scenario is
unfalsifiable. So this scenario and the script-swap lifecycle requirement stand
or fall together — flagging the dependency.

**Is 4.4's accepted-but-silent case the right test, or over-specified?** Right
test. A runner that accepts work and never acts is the most dangerous of the
three precisely because nothing errors. One gap: 4.4 does not check the waiting
agent is released. A leaked waiter passes once and fails under repeated flaps,
so assert eventual release, not only the fallback.

## Scope

Spec gate only. Nothing built, nothing run. `1.4` was unticked pending this PASS;
it may now be ticked.

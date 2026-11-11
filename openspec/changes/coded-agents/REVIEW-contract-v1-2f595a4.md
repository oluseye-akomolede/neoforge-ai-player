# Gate — contract v1 at 2f595a4

Rows: qitem-20261110112003-9e1b7f1978cea14e (and duplicate
qitem-20261110112006-653862bdb92e8fe6 — one review answers both)
Artefact: `openspec/changes/coded-agents/contract-v1.md` at commit `2f595a4`
(360 lines)
Date: 2026-11-10T11:22Z
Reviewer: minecraft-reviewer@minecraft
Verdict: **PASS**, with one item to surface to cardgame before the freeze.

Read from the rev: `git cat-file -t 2f595a4` = commit; every quotation below is
`git show 2f595a4:…`. `openspec validate --strict` valid, `show` clean, 13
requirements.

## The lead's check: does every spec:85 item exist with a schema?

`spec:85-92` mandates nine items. All nine are present and specified:

| spec item | where | assessment |
|---|---|---|
| tick delivery and cadence | §2.1 request/response, §7 `deadline_ms`, §9 item 1 | fully specified |
| transport | §1 protocol, DNS address, `Content-Type` | fully specified |
| runner↔server auth | §1 `Authorization: Bearer`, per-game token from a secret, **401 before parsing**, health exempt | fully specified |
| snapshot schema | §3 shared envelope, binding payload | fully specified |
| `api.*` shapes incl. rejection | §4.1 table, §4.2 `{ok:false, reason}` | fully specified |
| `script.get/put/logs` | §2 "not runner endpoints", `need_source` (§2.1), logs in tick result | **see below** |
| per-tick outcome classes | §6 ten-class fixed list + Minecraft state machine | fully specified |
| limits table | §8, 12 rows, each with value/unit/enforcement/on-breach | **exceeds** the mandate |
| (must not be adverbs) | every row numeric or explicitly "unstated for v1" | satisfied |

**The builder's two self-flagged caveats are both over-modest — neither is a
defect.** They offered `script.get/put/logs` and the fallback states as items
answered "by moving the responsibility rather than specifying a shape," and
invited me to say if that does not discharge the item. It does:

- `need_source` is a **specified interface**: a request field (`source`), a
  response status with its own shape, and explicit retry semantics — "No action
  is taken and no tick is consumed", plus the first-tick-after-restart case.
  The spec does not require REST nouns for script CRUD; it requires the contract
  to specify how source reaches the runner, and §2.1 does.
- §6 gives a **fixed class list** (the shared part) plus a stated state machine
  (`active`/`degraded`/`disabled`, 3-consecutive rule) on the game side, which is
  exactly what cardgame point 5 asked for. The requirement was that the runner
  not own a state machine, not that no state machine exist.

## The 8 cardgame decisions

All eight land where the row claims, and I read each site rather than the
index: 1→§9 item 1, 2→§4.1/§4.2/§9 item 2, 3→§1/§2, 4→§2.1, 5→§6, 6→§7,
7→§7, 8→§4.1/§9 item 5. No decision is silent.

> Naming note: §9 is a numbered **list of five decisions**, not subsections.
> The handoff's "section 9.1 / 9.2 / 9.5" means list items 1, 2 and 5. Cited
> that way here so a reader does not go looking for a `### 9.1` that does not
> exist (checked: `grep -n '9\.[1-9]'` on the contract returns nothing).

## The one thing that genuinely changes behaviour — and it is done correctly

Decision 2 replaces **"Host Calls Are Asynchronous"**, a requirement that had a
spec delta. My culture says a change that removes spec'd behaviour needs a delta
that says so, so I read the delta rather than the summary. `spec:284-290` names
the replaced requirement, enumerates the cost of the async design (second
transport, second auth leg in the opposite direction, an inbound endpoint per
game server, a callback timeout), states why returning actions needs none of
them, and — the part that matters most — **corrects the asyncify pin's
justification** rather than leaving a build pinned for a reason that no longer
holds. `spec:287-288` and §9 item 2 say the same thing independently. That is the
class of orphaned rationale that quietly decides things a year later.

## Verified facts

- `TICK_DELAY = 2.0` at `agent/config.py:89` — so §7's 250 ms rationale
  (12.5 % of the decision interval) is arithmetically right.
- The 51-name dispatch set at `agent/agent.py:2987` — a `match` statement, 52
  raw arms, 51 excluding `_`. Matches §4.1.
- The 12 limit rows exist with value, unit, enforcement point and breach
  outcome. This is **stricter than the spec's own table** (spec:112-125), which
  has no "on breach" column and no stack row; the contract adds both.

## One item for cardgame before the freeze — not a defect in the document

§7 gives `max_sandboxes: 32` "concurrent sandboxes **per runner instance**", and
§11 says "one runner instance serves both games". Those two together mean the 32
is a **pool shared between minecraft and cardgame**, while the table's per-column
framing reads as if each game has its own. Combined with §7's refusal policy —
over capacity the runner refuses a **new** bot with `429` and "never evicts a live
one" — whichever game fills the pool first locks the other out of starting new
bots, with no cross-game reservation and no fairness rule stated.

The document is internally consistent; the risk is in the *reading*. It belongs
in §10 "Open for cardgame" alongside the deadline and pod-selector items,
because cardgame will otherwise sign a contract whose capacity is jointly held.
Cheapest fix: one sentence in §7 or §10 stating the pool is shared and naming
what happens when both games want it. I am not failing the gate on this — the
numbers are marked "proposed, not measured" and the freeze is not until review
and the cardgame row, both of which are correctly stated as acceptance
conditions at `spec:94-95`.

## Scoping note on the accepted caveats

The builder listed two things they "could not verify and have not claimed":
cardgame's pod selector, and the proposed-not-measured capacity numbers. Both are
correctly marked as placeholders/proposals in the document. I am not treating
them as verified, and neither should cardgame.

## Scope

Document gate only. Nothing built, nothing deployed, no cluster writes.

# Spec gate — coded-agents (c867a8e)

Row: qitem-20261110100405-602bf62cf2f02486
Commit: c867a8e (spec only: proposal.md, tasks.md, specs/bot-coded-agents/spec.md; 318 insertions)
Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-10
Verdict: **FAIL — one blocker before task 1.4 is ticked**

Read from the commit, not the worktree. Owner decisions checked against the
owner's own words in `qitem-human-answer-181fe641fe26089fc36b`, not against the
builder's summary of them.

## What passes

**`openspec validate coded-agents --strict` → valid. `validate --specs
--strict` → 15 passed, 0 failed.** Both reproduced.

**ADDED is correct.** `openspec/specs/` has no `bot-coded-agents`; the
capability is new, so there is no MODIFIED-by-omission risk. `bot-xp-economy`
does exist as a live spec, which makes the XP separation point below load-bearing
rather than cosmetic.

**The owner's decisions are encoded faithfully, including the part the builder
did not claim.** The owner wrote "a daily cap for players on the server". The
spec makes it per-player, not per-bot, and says so with a scenario. I agree with
that reading — "for players" is the subject of the cap. Good call surfacing it.

**The mod-settings claim is accurate.** No `ForgeConfigSpec`/`ModConfigSpec`/
`registerConfig` anywhere in the tree (my grep returned nothing, and I treated
that as unproven until the positive control below), and the JSON convention is
real: `BotShop.java:22` → `config/aiplayermod-shop.json`,
`TransmuteRegistry.java:34` → `config/aiplayermod-transmute.json`,
`BotManager.java:82` → `config/aiplayermod-bots`. Speccing
`aiplayermod-scripts.json` alongside them is the right convention.

**The XP hole is closed, and it needed to be.** The proposal's
`not the mechanism` paragraph (`proposal.md:79-82`) is doing real work: an
`bot-xp-economy` capability is live, so a later reader could plausibly
reintroduce "earn hours from XP" as an extension of it. The sentence prevents
that. Keep it.

## BLOCKER — the per-player cap has no owner

The cap is specified as per-player, and two scenarios require an ownership
relation the product does not have:

- spec `:19-21` — "A player cannot read another player's script … THEN the
  request is refused"
- spec `:109-112` — "a player owning two bots has both run scripts … count
  against that player's single daily allowance"

**There is no bot-to-player ownership anywhere in the tree.** No `owned`,
`ownership`, `claimed_by`, `bot_owner` or `player_uuid` relation in
`openspec/specs/`, `agent/` or `src/`. `bot-identity/spec.md` specifies
identity *properties* (BotServerPlayer, survival mode, permissions) and says
nothing about who owns a bot. Bots are server-side entities driven by an agent
process; no player is their owner.

**The dashboard has no auth layer at all.** Every route is an unguarded
`@app.get`/`@app.post` on `/api/bots/{name}/…`. There is no user identity, no
session, no token check — so "refused" has nothing to refuse *on*. Spec `:19-21`
is not unimplementable for lack of effort; it is unimplementable as written,
because the resolving predicate does not exist.

**Correction, later the same day.** In a follow-up message I told the builder
that "mutating routes require the shared auth token
(`server.py:314-447`)". That was **false**, and the builder caught it.
`server.py:314` is an undecorated `@app.post("/api/command")`; a sweep of
`agent/` finds zero `Depends()`/`Security()`/auth middleware used to protect any
route, and the process binds `0.0.0.0:710`. The `MOD_API_KEY` call sites
(`api.py:7-8`, `telemetry.py:36`) are all **outbound** — the agent presenting a
key to the mod's HTTP API — which is what I misread as an inbound check. My
conclusion that no player can inject script text stands, but the reason is
**exposure, not authentication**: no dashboard Service exists, so the port is
reachable only by port-forward. Recorded here because the consequence was
product-level: the LLM-only requirement was resting on a mechanism that does not
exist. The commit `07904d1` now states it plainly in the spec instead.

This is the same failure class the builder flagged as its own worry (#3, "where
I could have invented the product"), and it is in the one thing the owner's
words did not settle: *which bots are a given player's*.

**Not a blocker, but decide it in the same breath:** the metering requirement
(`:79-84`) demands attribution to a player, and tasks 5.2 / 6.2 both depend on
it. The builder parked the *runner hosting* question (4.2) and left this one
unparked. The ownership question blocks more of step 5 and 6 than 4.2 blocks
step 4.

Needs an owner decision, not builder invention: is a bot bound to a player
(in-game player UUID, dashboard user, or nobody)? If nobody, the cap should be
specified per-bot now and revisited, and the "cannot read another player's
script" scenario should drop to "anyone with dashboard access can read any
script" — which is a product statement worth making explicitly.

## Finding 1 — the action count is wrong in two files

`proposal.md:53` and `tasks.md:13` both say **50 distinct actions / 51 `case`
labels**. Measured on this commit:

| measure | count |
|---|---|
| `case` labels, raw | 52 |
| `case` labels excluding the `_` default | **51** |
| quoted action names in those labels | 52 |
| **distinct action names** | **51** |

The one duplicate is `goto`, so both files are off by one in both numbers.

Their reading is plausible and nearly right: the first `case` label is
`case "goto" if "target" in p:` at L2987 — a guard arm. Counting *typed*
patterns gives 50 and dropping the guard arm from the name tally is defensible.
But the text says "`case` labels", and there are 51 of those. Fix the number or
fix the unit word.

Recorded honestly: my first parse printed 50, and that was my bug (I quoted a
display-formatted line). A first number is not a measurement.

**Why a count matters here:** tasks 3.2 requires proving an unknown action is
refused. If the dispatch set is miscounted in the spec, the test that proves
step 3.2 can be written against exactly the same misparse and pass while
leaving a real action unreachable from scripts.

## Finding 2 — `container` is in the dispatch set but absent from the examples

`proposal.md:53-55` gives examples "`goto`, `mine`, `craft`, `container_extract`"
and claims the list is "50 distinct actions". The surface includes `container`,
`container_insert`, `container_extract`, `list_recipes`, `craft_chain`,
`delegate`, `send_item`, `shop_buy`, `trade`, `conjure`, `meditate` — actions
with real consequences for other players (transfer, trade, delegation,
conjure).

The spec's action-bound requirement (`:49-52`) is a *ceiling*: scripts can reach
these because the LLM can. That is coherent, but it should be said out loud in
the spec, because "script acts through existing actions" reads as narrower than
it is. A player-watching read-only story plus scripts that can `delegate` and
`send_item` is a different security posture than the proposal conveys.

Not a blocker. Add one sentence to the scope of the action-bound requirement.

## Finding 3 — the read-only view contradicts a read-only script

Proposal `:91-93`: the view shows "the script as it actually runs", and spec
`:14-17` says "the source returned is the revision that bot is currently
executing". Separately, the model rewrites scripts every few minutes
(`proposal.md:57`).

So the player reads a snapshot that is already stale, and more importantly the
sentence "read-only" is doing two different jobs in this document — non-writable
by the player, and immutable once shown. They are not the same claim, and a
later implementer can satisfy one and violate the other. State which revision is
returned *and* that no history is kept, or specify history.

Minor, but it is exactly the sort of sentence that becomes a support question
later ("why did the script I read not match what my bot did?").

## On the blocked task 4.2

Correctly blocked and correctly marked. The reasoning ("if it is shared, the
wrong choice is a rebuild rather than a move") is sound, and refusing to design
the deployment manifest before the answer is the right call.

## What I could not verify

- Whether the owner meant per-player or per-bot. The owner said "for players";
  the per-player reading is defensible and I would keep it, but this is an
  inference from a Slack sentence, and the blocker above is what makes it
  consequential.
- Whether a separate "mod settings" UI exists outside this repo. In-tree there
  is only the JSON convention, as the builder said. I did not survey other
  repos or the server config on the cluster.
- Runtime behaviour of QuickJS sandbox limits. Spec-only; nothing to run.

## Required to unblock

1. Resolve the ownership relation (owner decision): bot↔player binding, or
   re-specify the cap per-bot and drop the cross-player read scenario.
2. Fix the action count in `proposal.md:53` and `tasks.md:13` (51 distinct / 51
   labels excluding the default, or restate the unit).
3. (Optional, non-blocking) one sentence on the action ceiling, one on revision
   history.

Task 1.4 stays unticked. No code until this passes.

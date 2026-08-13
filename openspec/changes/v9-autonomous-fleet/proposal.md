# v9 — The Autonomous Fleet (chunk anchoring · standing orders · fleet-wide orders)

## Why

v7 gave the player a seat in the network; v8 gave the network hands. Both
stop working the moment the player logs off: bots don't load chunks, so the
ME grid fragments, crafting machines freeze, and every directive that
touches the world silently degrades to no-ops. v9 is the difference between
"five bots I drive" and "an organization that runs while I sleep" — which
is precisely the capability the hive mod scales up. Every mechanism here is
a hive primitive built and proven at 5-bot scale first.

The whole 2026-08-11 session is the evidence file: the 4,826-node grid
shrank to 1 node when the player left; a crafting job sat in `CRAFTING`
for half an hour because the crusher's chunk was cold; force-loading by
hand via rcon was the workaround every single time.

## Feature 1 — Chunk anchoring

A bot may hold a **chunk ticket** covering a small radius around itself
(3×3 chunks), like a player does. Opt-in per bot, and **metered**: holding
an anchor drains bot XP per hour (config `anchorXpPerHour`, default 2
levels). XP is the fleet's universal currency; keeping the world warm
should cost something or every bot anchors forever and the server pays.

- **L1**: `AnchorManager` — per-bot ticket add/remove via
  `ServerLevel.getChunkSource().addRegionTicket` with a custom ticket type;
  tickets follow the bot across teleports (drop old region, take new);
  XP drain on a 1200-tick cadence with an honest broke-bot behavior:
  anchor drops, one chat line, telemetry event. Released on despawn and
  server stop; **persisted** in bot state (a restart must not silently
  freeze a fleet that believed it was anchored).
- **API/directives**: `ANCHOR_ON` / `ANCHOR_OFF` directive kinds (catalog +
  L2 + direct dispatch); `anchored` + burn rate surfaced in `/bots`,
  `me_status`, and the overlay Status tab (⚓ glyph on the fleet row).
- **Overlay**: anchor toggle button on the unit Status tab, with the
  running XP cost shown next to it — informed consent, always.
- **Guardrail**: fleet-wide anchor cap (config, default 5 bots × 9 chunks);
  the 6th request is refused with the reason.

**Provable**: player logs off; an anchored bot at the base keeps the grid
whole (`me_networks` shows the full node count with zero players online);
a CRAFT_REQUEST completes end-to-end with nobody on. The forceload rcon
crutch is retired.

## Feature 2 — Standing orders

A **standing order** is a persistent watcher: a condition over observable
state, an action to fire when it breaks, and a report when it settles.
The canonical one is the quantum helmet's shopping list turned permanent:
"keep ≥ 10,000 matter balls in the network."

- **Model** (agent-side store, JSON on the agent volume — survives
  restarts): `{id, bot, watch: {type: me_count|vault_count|xp_level,
  item?, threshold, comparator}, action: {kind, params} | {text}, cooldown,
  enabled, last_fired, last_result}`.
- **Loop**: a `_standing_worker` evaluates each order on a 30 s cadence
  (me_count via the bot's terminal — anchored bots make this real). When a
  condition breaks AND the bot is idle AND the cooldown has lapsed, the
  action enters the SAME order lane as everything else (direct dispatch for
  typed kinds, `execute_task` for text) — so all L4 triggers still apply.
  Failures back off exponentially and land ONE inbox item, not a nag storm.
- **Creation**: from the Cmd tab (a "make this standing" checkbox on the
  builder: condition fields appear), or natural language through the TEXT
  lane — L3 gets a `STANDING_ORDER` vocabulary entry that emits the model
  above (ASK_PLAYER on ambiguous thresholds).
- **Overlay**: a **Standing** sub-tab per unit: each order shows condition,
  current reading vs threshold, last fired, last result; toggle and delete
  in place. Destructive actions (delete) use the two-step confirm.
- **Guardrails**: per-bot cap (default 4); XP-spending actions respect a
  per-order XP budget field; standing CRAFT_REQUESTs refuse to fire while
  the previous one is still `CRAFTING` (one job per bot stands).

**Provable**: set "keep ≥ 32 quartz dust"; drain the network below 32;
the watcher fires a CRAFT_REQUEST unprompted, the grid crafts, the count
recovers, the Standing tab shows the cycle, and a telemetry line narrates
it in the Mind tab.

## Feature 3 — Fleet-wide orders

One order, many bots. `"fleet"` (and later `"group:<name>"`) becomes a
valid address in the existing order lane — nothing new on the wire.

- **Resolution**: the mod's `resolveBot` seam gains `resolveTargets(addr)`
  → list; `"fleet"` = all living bots. `SubmitOrder` to `fleet` fans out
  ONE OrderStore entry per bot, tagged with a shared `fleet_id` so the
  overlay can render the umbrella.
- **Typed orders** fan out verbatim (everyone gets `ME_STORE all`).
  **TEXT orders** get a partition step first: the agent runs ONE L3 call
  with the fleet's capability profiles + holdings summaries in context,
  emitting per-bot assignments ("Tiller: crops; Forge: ores; …"), each of
  which then runs through the normal per-bot lane. Partition failures fall
  back to verbatim fan-out — degraded is better than dead.
- **Capability profiles**: `agent/profiles/*.json` gains a `capabilities`
  list (mine/farm/craft/fight/scout) the partitioner cites. This is the
  hive's role system in embryo.
- **Overlay**: the Fleet tab gets an order strip (same builder + text box
  as a unit's Cmd tab, addressed to `fleet`); a fleet order renders as one
  umbrella row with per-bot status chips (RUNNING/COMPLETED/FAILED per
  member), expandable to the detail of each.
- **Guardrails**: fleet TEXT orders that would move items out of ANY vault
  echo the plan into the inbox for a one-click confirm before dispatch
  (destructive-at-scale deserves one gate); per-bot failures never abort
  siblings.

**Provable**: "fleet: store your non-essential items" — five bots, five
independent completions, one umbrella row; then "fleet: restock the
network" partitions differently per capability profile.

## Sequencing

Anchoring first (everything else is honest only in warm chunks) → standing
orders (needs anchoring to watch ME state) → fleet orders (needs nothing
but benefits from both). Each lands with its headless proof before the
next starts; the in-game proofs batch into one player session.

## Hive seam notes

Anchor tickets, standing-order stores, and fleet addressing all key by bot
UUID (the v7 seam). The hive mod lifts: ticket metering → drone upkeep;
standing orders → drone job loops; fleet partition → swarm tasking with
groups as first-class addresses. The two hard-won disciplines (generations
+ write-capture for parallelism; login-event announcement for
`level.players()` entrants) are inherited constraints, not options.

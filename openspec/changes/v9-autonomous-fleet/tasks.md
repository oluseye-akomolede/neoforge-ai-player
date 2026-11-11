# v9 tasks

Reticked 2026-09-29 against the code on `main` (`dd88be0b3a8033f699229354b09858b9fadf751e`).
Boxes below are the original ticks; each ticked box now carries a file/line
citation where the code can be pointed to in **this repo** (`neoforge-ai-player`,
which builds both the agent and the `aiplayermod` mod jar). Items that live only
in the mod jar, or that need a live player/environment, are called out — see
"Not verified at archive" in `proposal.md`.

## Phase 1 — chunk anchoring

- [x] `AnchorManager`: ticket distance 3 (level 30, entity-ticking core),
      follows the bot across teleports/dimensions on a 100-tick cadence;
      released on despawn + server stop
- [x] XP metering (env `AIPLAYER_ANCHOR_XP_PER_HOUR`, default 2/hr);
      broke bot → anchor collapses with chat + log
- [x] Persistence in bot state JSON (re-anchors on load, warns on refusal)
- [x] Fleet anchor cap (env, default 5) with honest refusal
- [x] `anchor_on`/`anchor_off` API actions + ANCHOR_ON/ANCHOR_OFF catalog
      kinds via direct dispatch; L2 kinds + aliases; L3 vocabulary note —
      agent side: `agent/agent.py:3155` handles `ANCHOR_ON`/`ANCHOR_OFF`;
      `agent/dashboard/schemas.py:125` catalog entry;
      `agent/l3_planner.py:642` L3 vocabulary
- [x] Surfacing: `/bots`.anchored + fleet row ⚓ + Status-tab toggle
- [x] **Headless proof PASSED (2026-08-11)**: forceload removed entirely,
      zero players online, Forge + Scout anchored → grid at 4,864 nodes,
      CRAFT_REQUEST 8x quartz dust delivered end-to-end. The world is
      warm because the fleet keeps it warm.

## Phase 2 — standing orders

- [x] Store lives in the MOD (`StandingStore`, mailbox pattern like
      orders/talk), persisted to `aiplayermod_standing.json` with the
      world; HTTP GET defs / POST reports / PUT create
- [x] `_standing_worker` (agent): 30 s cadence, idle-only firing,
      exponential backoff, inbox escalation after 3 straight failures —
      `agent/agent.py:3207` `_standing_worker`, started at
      `agent/agent.py:4194`
- [x] Watch types: me_count, vault_count, xp_level
- [x] Cmd tab ⏲ Keep button (order → permanent invariant with threshold
      box); Stand sub-tab: condition, live reading, last fired/result,
      pause toggle, confirm-gated delete
- [x] L3 guidance points "keep X stocked" requests at ⏲ Keep (creation
      stays a deliberate player act in v1)
- [x] Guardrails: per-bot cap 4 (honest refusal), idle-only firing (no
      double CRAFT_REQUEST — active directive blocks), backoff
- [x] **Headless proof PASSED (2026-08-11)**: standing order s1
      (dust_quartz ≥ 32, network at 24) fired ONE CRAFT_REQUEST
      unprompted; anchored machines crafted; count restored to 32 before
      the monitoring loop's first sample. Fired exactly once. The fleet
      noticed, acted, and stopped — nobody asked it to.

## Phase 3 — fleet-wide orders

- [x] `fleet` address in SubmitOrder: typed orders fan out verbatim under
      a shared fleet id; TEXT orders travel whole (bot="fleet") to the
      agent's partition step
- [x] `partition_fleet` (one L3 call, personas + holdings in context,
      per-bot assignments, "skip" allowed, verbatim fan-out fallback) —
      `agent/l3_planner.py:704` `partition_fleet`; called from
      `agent/agent.py:3510` with verbatim fallback on failure
- [x] Fleet tab order box + umbrella rows with per-bot status chips
      (fleetId on the OrderLine wire)
- [x] Inbox confirm gate (ONE confirm) for fleet TEXT orders touching
      inventories
- [x] **Headless proof PASSED (2026-08-11)**: typed fan-out — five
      ME_STORE orders dispatched; TEXT partition — "everyone check in"
      split into five tailored assignments, five plans, five COMPLETED.
- [ ] **In-game batch** (PLAYER — needs in-game order issue): the v8 canonical orders retried under
      v9 — "fleet: store non-essentials" plus the standing restock built
      from the quantum helmet's missing-ingredient list; verify anchor
      persistence across the NEXT restart (this one shut down on the
      pre-fix jar)

## Not verified at archive

- Everything under **"Headless proof PASSED (2026-08-11)"** is a recorded run
  that is not reproducible from the tree; the code paths it exercised are
  present on main, but the runs themselves are the evidence and are not in this
  repo.
- The **anchor ticket mechanics** (`AnchorManager`, ticket distance, XP drain
  cadence, persistence, fleet cap) and the **mod-side `StandingStore`** live in
  the `aiplayermod` Java sources (`src/main/java/com/sigmastrain/aiplayermod/`),
  which this repo builds into `aiplayermod-1.0.0.jar`. They are live only if the
  deployed server jar carries them; that is a deployment fact, not a code fact,
  and is not proven here. What *is* pointable in this repo is the agent side
  (directive handling, the standing worker, the fleet partition call), listed
  with citations above.
- The single open task (the in-game batch) needs a player to issue orders and
  is deliberately left open.

# v8 — Inventory & Menu Directives (LLM-enabled overlay operations)

## Why

The v7 overlay gives the player fine *manual* control. v8 makes the same
surface *conversational*: natural-language orders about a bot's inventory,
equipment, and the ME fabric, planned by L3 and reviewed through the same
L4 flow as everything else. Canonical orders (player's own words):

- "Mystic, put all of your non-essential items into your vault or into ME
  storage. I don't care which."
- "Scout, clean up your vault. Put everything except for weapons into ME
  storage."
- "Axiom, submit crafting requests for a full set of quantum armor. Equip
  the armor so that all bots can now channel it for themselves."

Everything built here transfers to the hive mod's overlay.

## Decomposition

Two genuinely new capabilities; everything else is wiring:

1. **Classify-and-move**: "non-essential", "everything except weapons" are
   L3 judgment calls over the bot's inventory manifest, emitted as plans of
   EXISTING verbs (VAULT_STORE/WITHDRAW, ME_STORE/WITHDRAW, DROP,
   EQUIP_ALL). The LLM classifies; the mod moves.
2. **AE2 autocrafting**: "submit crafting requests" = the grid's
   `ICraftingService` through the worn wireless terminal —
   calculate → submit job → poll status. Entirely new in `WirelessME`.

## Design

### Entry point (built in v7 Phase 7c)

The equipment window and the unit Command sub-tab both feed the
`/telemetry/orders` queue. v8 adds a free-text chat strip to the equipment
window (`BotEquipmentScreen`) — text orders enter the SAME queue with the
bot's inventory manifest attached as planning context.

**Talk/Order split stays explicit**: the equipment chat is an ORDER surface
(plans happen). Talk remains conversation (no plans, ever).

### The chain, layer by layer

- **L1 (mod)**: `WirelessME.requestCraft(access, itemId, count)` +
  `craftJobStatus(...)` via reflective `ICraftingService`; new
  `CRAFT_REQUEST` DirectiveType + behavior (submit, then poll to
  completion or honest failure "no pattern for <item>", "missing
  ingredients: …"); `curios_equip` (from Phase 7b); API actions
  `craft_request`, `craft_status`.
- **L2 (l2-mcp)**: `KNOWN_KINDS` += `ME_STORE`, `ME_WITHDRAW` (wired at L1
  since v6/v7 but MISSING from L2 today — L3 plans using them get flagged
  `unknown_kind`), `CRAFT_REQUEST`. Aliases: AUTOCRAFT, ME_CRAFT,
  REQUEST_CRAFT → CRAFT_REQUEST; ME_DEPOSIT → ME_STORE, etc.
- **L3 (planner)**: new prompt section for inventory management — the
  inventory manifest arrives in context; classification guidance
  (essential = current directive's tools + weapons + food + the terminal
  itself unless told otherwise; "I don't care which" = prefer ME when the
  terminal is online, vault otherwise); CRAFT_REQUEST vocabulary with
  the rule that a crafting subtask is not COMPLETED until the job reports
  done.
- **L4 (player)**: nothing new to build — orders route through
  `execute_task`, so ambiguous-item, attempts-exhausted, veto,
  ASK_PLAYER, and timeout triggers all land in the existing inbox.
  Expected new traffic: "which of these count as weapons?" style rulings.
- **L5**: unchanged (advisory, L4-reviewed).

### Destructive-order posture

"Clean up your vault" can destroy value if L3 misclassifies. Guardrails:
(1) DROP is never planned from an inventory order unless the order says
"drop"/"discard" explicitly — moves go to vault/ME where they are
recoverable; (2) the plan summary lands in the Mind tab before execution
(existing telemetry); (3) L3 is prompted to ASK_PLAYER when the
classification affects > half the inventory.

## Verification (provable, in the player's words)

Each canonical order above, verbatim, in-game:
1. Mystic's inventory visibly split into vault/ME, essentials retained.
2. Scout's vault contains only weapons afterward; everything else is in ME
   (searchable via the fixed `me_search`).
3. Axiom's craft request appears in the AE2 grid, completes, armor equips,
   and another bot successfully channels a piece of it.

## Landed early (2026-08-11, pulled forward by live play)

- **The TEXT order lane has UI**: Talk tab split into Chat | Cmd (chat
  converses, Cmd plans+executes natural language), and the equipment window
  gained a chat overlay (💬 button, tooltip-level Z) that submits TEXT
  orders for the bot whose inventory you are looking at.
- **Builder orders are direct dispatch** — typed kind+params go straight to
  L1, no L3 reinterpretation (the CHANNEL→quartz-block incident).
- **PROVISION_TERMINAL**: `/server/me_networks` enumerates AP-bearing
  networks via AE2's TickHandler grid list; `provision_terminal` finds or
  conjures (XP cost) a wireless terminal, links it to the chosen/random
  network, charges it, wears it. Chat-planned = random network (design
  ruling); Cmd tab = network dropdown, options pushed by the agent.
- **SHARE_LOCATION**: one-shot order writing the bot's current position
  into the orderer's TemPad.
- **Inbox is an editor now**: escalations carry the failing directive
  (wire: InboxItem.directiveJson); the overlay renders its fields editable;
  ▶ Rule / ? L5 send a JSON envelope {directive, note} — replan guidance
  gets the corrected directive verbatim, L5 consults on the corrected
  picture.
- Channel commits use the CHANNEL directive (auto-meditates); dropdowns
  everywhere are type-to-search.

**AE2 autocrafting (CRAFT_REQUEST) implemented 2026-08-11**:
`WirelessMECrafting` drives `ICraftingService` reflectively — craftables
via `getCraftables(AEKeyFilter.none())`, calculation via
`beginCraftingCalculation` (simulation requester is a two-method
`java.lang.reflect.Proxy`; `REPORT_MISSING_ITEMS` so shortfalls fail with
the missing-ingredient list), submission via `submitJob(plan, null
requester, auto CPU)` — products land in NETWORK storage, the same
convention as AE2's own terminals. One job per bot; the CRAFT_REQUEST
L1 behavior polls the crafting link once a second and completes only when
the link reports done ("submitted" is not "crafted"); interrupting the
directive cancels the grid job. Cmd-tab dropdown options come from
`me_craftables` (Scout's terminal) at schema-push time.

**Also fixed en route**: bot state persistence never saved worn curios —
a restart stripped every terminal the fleet was wearing. `saveState`/
`loadState` now round-trip curios (with never-destroy fallback into
inventory/vault if the slot layout changed).

**Headless verification (2026-08-11 early morning)**:
- Root cause of every calculation failing as "missing: <the request>" found
  and fixed: `CraftingTreeNode.buildChildPatterns` silently builds ZERO
  patterns when `simRequester.getGridNode()` is null — the requester proxy
  now returns the grid's pivot node.
- **Honest missing-ingredients failure proven**: quantum helmet request
  walked the real dependency tree — "missing: 10048x matter_ball, 121x
  quartz_glass, 16x ancient_debris, 372x silicon, 150x glowstone_dust…"
- **Honest no-pattern refusal proven**: stick request refused cleanly at
  the gate (EMC-bridge patterns come and go with module state).
- **Submission + grid execution proven**: 8x mekanism:dust_quartz
  calculated, submitted, link live, CPU crafting — the DONE transition
  awaits the base machinery actually processing (world state, not code).
- Fleet fully ME-online: all five bots wearing linked, charged terminals
  via PROVISION_TERMINAL (stack-drain and dimension bugs fixed en route;
  worn curios now persist across restarts).

Still open: observe one DONE transition; the three canonical in-game
proofs in the player's verbatim words.

## Sequencing

Gated on v7 Phase 7 (interface feature-complete). Then: L2 kinds (trivial)
→ WirelessME crafting (spike first: reflective ICraftingService against
the real grid) → L1 CRAFT_REQUEST behavior → L3 prompt work → equipment
chat strip → in-game proofs.

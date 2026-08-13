# v7: The player joins the network

## Why

Every layer of this system talks to every other layer except one. L1 reports
to L2, L2 translates for L3, L3 plans. The player stands outside it all,
typing sentences into chat and reading a web dashboard on a phone.

That is an operator, not a participant. This change puts the player *inside*
the pyramid as a layer with a seat, an inbox, and authority — reachable from
inside the game by a hotkey rather than by alt-tabbing to a browser.

## The ladder, revised

```
L1  mod-side        ground truth, deterministic
L2  python agent    translation, repair, provisioning
L3  qwen2.5:14b     planning — and now conversation
L4  THE PLAYER      inbox, arbiter, review gate
L5  OpenAI          summoned by L4, answers TO L4
```

**The invariant that makes this work: nothing from L5 travels down the chain
unreviewed.** L4 is a gate in both directions. L3 escalates up to the player;
the player may answer, may edit, or may spend a call on L5 — but L5's answer
returns to the player's inbox for approval before it becomes an order. The
expensive external model stays advisory. The player stays sovereign.

This also fixes a live defect. l2-mcp already *detects* ambiguity and then
guesses anyway:

> `ambiguous_item: steel_ingot` → candidates `[mekanism, immersiveengineering, gtceu]` → picks one

Detection without a recipient is a dead end. L4 is the recipient.

### Inbox item types

Every one of these already exists as a condition the system detects and
currently swallows:

| Trigger | Today | With L4 |
|---|---|---|
| ambiguous item/mob id | guesses | asks for a ruling |
| criteria provably impossible | evidence-gated rewrite | asks |
| attempts exhausted (3/3) | replans blindly | shows the failure, asks |
| directive timeout (15m) | fails silently | surfaces the wedged behavior |
| L3 emits `ASK_PLAYER` | n/a | new vocabulary |

Each item carries the bot, the context, the proposed action, and four
responses: **approve**, **edit and submit**, **escalate to L5**, **cancel**.

## Talk vs Order

Today every sentence a player types becomes a plan. Casual remarks spawn
orchestrator runs. The split becomes explicit:

- **Order** — goes to the planner, becomes subtasks and directives. The
  existing path.
- **Talk** — a direct conversation with that bot's L3, carrying its persona,
  world state, memory hits, and current directive as context. No plan, no
  criteria, no dispatch. A new agent endpoint (`/bot/{name}/converse`) doing
  a single chat call.

L3 is powerful and mostly idle. Talking to it is free headroom, and "ask Scout
what it makes of the terrain" is a different act from "order Scout to build."

## The overlay

Hotkey; tap to latch, hold to peek. Never pauses — this is a live world.
Number keys jump between bots.

| Screen | Contents |
|---|---|
| **Fleet** | one row per bot: hp, xp, dimension, current directive, progress, inbox badge |
| **Command** | live directive card, interrupt, queue, directive builder, crosshair targeting |
| **Inventory** | carried grid, vault (searchable), curios row, channel panel with XP cost preview |
| **Mind** | thought stream — L1 phase → L2 retries → L3 plan/criteria/verdict; memory hits; replay scrubber |
| **Talk** | conversation with that bot's L3 |
| **Inbox** | the L4 queue |
| **Network** | agent connectivity, L3/L5 status, latency |

Two details worth stating because they are the reason this beats the web UI:

- **Crosshair targeting** — look at a block or entity, press a key, it fills
  the directive's target. A browser cannot do this.
- **Interrupt-and-channel** — pick an item, see its cost from
  `ConjureAction.COST_TABLE` against the bot's actual XP, commit. The
  directive it interrupts is named on the button.

The directive builder is generated from `agent/dashboard/schemas.py`, the
same source that drives the web dashboard, so the two cannot drift.

## Jack in

`setCameraEntity` onto a bot: your view becomes its view. Cheaper than a
render-to-texture viewport — it is the ordinary render, relocated — and it
makes the premise literal. You do not watch the network, you enter it.

**Your body stays in the world and stays vulnerable.** No auto-eject on
damage. Jacking in is a real risk, which is what makes it a mechanic rather
than a camera toggle.

### Spike 3 finding (from decompiled 1.21.1 source)

The vanilla server-side camera, `ServerPlayer.setCamera` (line 1617),
**teleports the player's body to the camera target** and hands movement
tracking to the camera chunk source. That is how /spectate works — and it
is exactly what "body stays vulnerable where you left it" forbids. Vanilla
also gates it on spectator mode (`SpectateCommand` throws
`ERROR_NOT_SPECTATOR`).

Consequence: jack-in cannot ride the vanilla server camera. It must be a
**client-side possession**: a `ClientboundSetCameraPacket`-equivalent sent
by our own S2C packet, applied via `Minecraft.setCameraEntity` on the
client only, while the server continues to tick the player's real body in
place. The server never learns the camera moved — which is also the
anti-cheat-friendly shape. Input capture (so WASD stops moving the real
body while jacked in) is client-side too.

### Cross-dimension possession (design intent, user directive)

Same-dimension-only is not acceptable: jacking into a bot in the End from
your base in the overworld is the point. Client-side-only possession cannot
do this — the client would have to load a dimension it is not in.

The design that satisfies both requirements is **the husk**. On jack-in:

1. A fake-player shell — the same infrastructure the bots are built on —
   spawns at the player's exact position with the player's skin profile,
   inheriting position and hitbox. This is the body you leave behind.
2. The real player rides the vanilla spectate path to the bot
   (`setCamera` teleport + camera chunk streaming — cross-dimension
   rendering handled entirely by vanilla, zero custom chunk code).
3. Damage to the husk is mirrored to the real player, wherever their
   camera is. **If the husk dies, the player dies.** No auto-eject; the
   husk does not fight back. Vulnerability preserved exactly.
4. Eject teleports the player back to the husk's position and despawns it.
   Server restart or logout force-ejects.

The fiction writes itself: you do not watch the network, you leave your
body to enter it. The mod's core competency — fake players — is what makes
the mechanic cheap: the husk is a bot with no brain.

## Curios, and the ME network

Bots are full `ServerPlayer`s in the player list, so they should accept a
Curios inventory. Giving them one is worth doing on its own — charms, belts,
and rings are a large slice of this pack's progression that bots currently
cannot touch.

The reason it matters more than that: **`ae2wtlib` already registers wireless
terminals as curio items.** From its own `data/curios/tags/item/curio.json`:

```
ae2:wireless_crafting_terminal
ae2wtlib:wireless_pattern_encoding_terminal
ae2wtlib:wireless_pattern_access_terminal
ae2wtlib:wireless_universal_terminal
```

A bot wearing a linked Wireless Universal Terminal is a bot connected to the
ME network from anywhere in range. Today `MEStoreBehavior` calls
`AE2Compat.findNearestMEInterface(level, pos, radius)` — ME access is
**proximity-based**, so a bot in the Nether cannot reach storage. Resolving
the grid from a worn terminal instead removes the leash entirely.

The consequence is the interesting part: bot vault, ME network, and player
inventory become one logistics fabric, and the overlay's Inventory tab is the
console for it. "Pull 64 certus quartz from the network into Forge, in the
Nether" becomes a single action.

### What is confirmed vs. what needs a spike

Confirmed by inspection:
- Curios 9.5.1 is in the pack
- ae2wtlib tags four wireless terminals as curios
- bots are real `ServerPlayer`s in the player list
- `ME_STORE`/`ME_WITHDRAW` directives already exist, gated on `isAE2Loaded()`

### Spike 1: ANSWERED — Curios attaches to fake players (live, 2026-08-08)

`CuriosApi.getCuriosInventory(bot)` on a running bot returned a full
inventory: **48 slots across the pack's whole slot vocabulary** (`curio`,
`ring`, `necklace`, `belt`, plus mod slots — `klein_star`, `qio`,
`mega_slot`, `spell_book`, …), and a simulated insert was accepted. No
join-path workaround needed; bots are first-class Curios wearers as-is.

Two side findings from the same session:
- `/give <botname>` **silently no-ops** — vanilla selectors don't resolve
  fake players. Bots acquire items through their own economy (conjure
  proved it live: `ae2:wireless_terminal` for 8 levels) or transfers.
- Bug found: `vault_withdraw` into a **full** pack reported
  `withdrawn: 1` while the item actually bounced back to the vault.
  Needs an honest partial/failure result. (Tracked for Phase 2.)

### Spike 2: ANSWERED — real ME access from a carried terminal (live, 2026-08-08)

The full chain ran on the test server with a minimal rig (creative energy
cell + wireless access point):

1. Scout **conjured** `ae2:wireless_terminal` — 8 levels, the bots' own
   economy, since `/give` can't reach fake players
2. `LINKABLE_HANDLER.link(stack, GlobalPos)` bound it to the access point
   — programmatic, no right-click, no GUI
3. `injectAEPower` charged it to 1.6M AE
4. `getLinkedGrid()` → `appeng.me.Grid`; `getStorageService().getInventory()`
   → `NetworkStorage`
5. **From the Nether**, same terminal, overworld AP: `grid_resolved: true`

A bot can join the ME network from another dimension. The one honest
caveat: the rig sat in spawn chunks (always loaded), so whether a bot's
own presence anchors an AP chunk is unverified — chunkloaded bases make
the question moot in practice.

### Spike 2 detail (decompiled AE2 19.2.17)

The GUI-free path exists and is public:

```
WirelessTerminalItem.getLinkedGrid(stack, level, errConsumer) → IGrid
grid.getStorageService().getInventory()                       → MEStorage
```

Decoding `getLinkedGrid`: stored `GlobalPos` → dimension → ticking block
entity → `IWirelessAccessPoint.getGrid()`. **No distance or dimension
check on the holder.** Range enforcement lives one layer up, in
`WirelessTerminalMenuHost.updateConnectedAccessPoint` (per-access-point
`distanceSquared` vs `remainingRangeSquared`) — a layer the bot path never
constructs. Consequences:

- Range and idle power become **our policy**, not AE2's. Decision: honor
  power (`usePower`/`hasPower` are public), make range a config knob
  rather than silently shipping infinite reach.
- The access point's chunk must be ticking (`Platform.getTickingBlockEntity`
  returns null otherwise) — cross-dimension works only if the AP chunk is
  loaded (chunkloaded base = fine).
- `IGridLinkableHandler.link(stack, GlobalPos)` is also public: bots can
  link a terminal to an access point programmatically. A LINK_TERMINAL
  action needs no GUI either.

If Curios does not attach to fake players, the ME half still works from a
terminal in the bot's normal inventory — the curio slot is ergonomics, not
the mechanism.

## What Changes

- **NEW client↔server packet layer.** The mod has none —
  `grep PayloadRegistrar` returns nothing, and vanilla container sync is the
  only channel that exists today. Everything here depends on it.
- **NEW agent→mod telemetry.** The mod knows only L1. Plans, criteria and
  reasoning live in the agent, which *polls* the mod. A reverse channel
  (`POST /telemetry/plan`, cached per bot, forwarded to subscribed clients)
  is required before the Mind tab or the Inbox can exist.
- **bot-brain**: directive queue with insert-ahead; pause/resume.
- **bot-inventory**: curios slots; ME access via worn terminal.
- **l3-spec-driven-planning**: `ASK_PLAYER` vocabulary; conversational
  endpoint separate from the planner.
- **dashboard**: schemas become the shared source for both UIs.

## Non-Goals

- **Multiplayer permissions.** Single owner by decision — no ownership model,
  no per-player scoping. The seam is kept clean for the hive mod, but nothing
  is built for it here.
- **Render-to-texture bot viewport.** Possession is cheaper and better.
- **Mobile parity.** The web dashboard keeps that job.
- **L5 acting autonomously.** It answers to L4 and only to L4.

## Verification

Pending.

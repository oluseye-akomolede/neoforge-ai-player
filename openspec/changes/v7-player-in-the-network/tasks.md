# v7 tasks

Ordered so each phase is independently useful and provable in-world.

## Phase 0 — spikes (do these before committing to design)

Three unknowns can each invalidate a chunk of the plan. Answer them cheaply
first; none needs UI.

- [x] **Curios on a fake player.** ANSWERED live: inventory present, **48
      slots** including `curio` (where wtlib's terminals go), simulated insert
      accepted. No workaround needed. Bonus findings: `/give <bot>` silently
      no-ops (fake players invisible to selectors — conjure works instead),
      and `vault_withdraw` into a full pack lies (`withdrawn: 1` but bounced;
      fix in Phase 2).
- [x] **Grid from a carried terminal.** ANSWERED live, end to end: Scout
      conjured `ae2:wireless_terminal` (8 levels), `LINKABLE_HANDLER.link()`
      bound it to an access point programmatically, `injectAEPower` charged it
      to 1.6M AE, and `getLinkedGrid()` resolved `appeng.me.Grid` →
      `NetworkStorage` — **no GUI, no proximity**. Then from the NETHER, with
      the terminal linked to the overworld AP: `grid_resolved: true`. Range and
      idle power are enforced only by `WirelessTerminalMenuHost`, which this
      path never constructs — so they become our policy (decision: honor
      power, make range a config knob). Caveats: the AP chunk must be ticking
      (test rig sat in spawn chunks, so bot-as-chunk-anchor is unverified);
      curio-slot equip not yet exercised (slot exists per spike 1 — the
      terminal worked from a plain inventory slot, which is the fallback the
      proposal named).
- [x] **Camera possession.** ANSWERED from decompiled source, design changed:
      `ServerPlayer.setCamera` TELEPORTS the body to the target (that is how
      /spectate works) and requires spectator mode — incompatible with a
      vulnerable body. Jack-in must be client-side: our own S2C packet applies
      `Minecraft.setCameraEntity` locally; the server keeps ticking the real
      body in place. Same-dimension only in Phase 5 (bot must be within client
      tracking range). Input capture is client-side.

Record findings in the proposal before Phase 1.

## Phase 1 — the pipe

Nothing exists here; this is the foundation everything else sits on.

- [x] `PayloadRegistrar` via `RegisterPayloadHandlersEvent` — registered
      `.optional()` so a client on a stale jar can still connect
- [x] C2S: `OverlaySubscribe(on)`, `InterruptDirective(bot, directiveId)`
- [x] S2C: `FleetSnapshot(List<BotEntry>)`, `ControlAck(ok, message)`
- [x] Subscription model — snapshots only to players with the overlay open,
      4 Hz (`SNAPSHOT_INTERVAL_TICKS=5`), immediate first frame on subscribe,
      unsubscribed on close and on logout. No broadcast.
- [x] Keybind (default **H**) + overlay shell, tap-to-latch / hold-to-peek
      (400 ms threshold), non-pausing, translucent — no vanilla blur
- [x] Fleet screen: rows with hp bar, dimension, position, directive summary
      + status glyph; rows clickable; 1–9/0 tab switching
- [x] Unit screen: directive card (id, type→target, phase, status, state
      line) + **Interrupt** wired to the id-scoped `cancelDirective` (D3 race
      guard applies); ack surfaces in the overlay footer
- [x] `BotBrain.peekDirective()/stateLine()/currentPhase()` accessors
- [x] **In-game proof** — player confirmed live (2026-08-08): overlay opens,
      fleet streams, interrupt works.

**Provable:** open overlay in-game, watch a directive tick, cancel it. ✔

## Phase 2 — fine control over matter

- [x] Unit sub-tabs: Status | Vault | Channel; per-bot state resets on switch
- [x] Equipment… button on Status → opens the existing `BotEquipmentMenu`
      (same `SimpleMenuProvider` path as bot right-click)
- [x] Vault tab: live search (server-side query on `effective_inventory`,
      100-entry page, sorted by total), scrollable list, click-to-select,
      Stow 64 / Take 16 / Take 64 / Stow all
- [x] Channel tab: item + count fields, **Quote** (server resolves the id,
      prices via `ConjureAction.costFor` → `TransmuteRegistry` → default,
      returns bot's actual XP and affordability), commit disabled until an
      affordable quote exists
- [x] **Interrupt-and-channel** — the quote names the directive it would
      displace ("would interrupt: MINE #42"); the interrupt travels with the
      quoted directive id so the D3 guard drops stale interrupts
- [x] `vault_withdraw` honesty bug fixed — `deposit()` zeroes the stack it
      absorbs, so `withdrawInto` counted bounced items as moved; leftover is
      now read before re-deposit ("pack full — nothing withdrawn" ack)
- [ ] Drag: player ↔ carried ↔ vault ↔ another bot's vault (deferred —
      button ops cover the flows; true drag needs a container menu)
- [ ] Directive builder generated from `agent/dashboard/schemas.py`
- [ ] Crosshair targeting to fill target params
- [ ] **In-game proof**: interrupt a MINE, channel 32 quartz, resume

**Provable:** interrupt a MINE, channel 32 quartz into the bot, resume.

## Phase 3 — L4

Requires the reverse telemetry channel; that is the bulk of the work.

- [x] Mod endpoint `POST /telemetry/event`; per-bot ring buffer
      (`TelemetryStore`, 100 events, open type vocabulary so the agent can
      add transitions without a mod release)
- [x] Agent pushes: plan created, subtask start (+criteria), every directive
      result, criteria verdicts (the exact evaluator reason strings), L2
      retries, replans, plan finalized. Fire-and-forget with a 60 s mute on
      endpoint failure — telemetry can never slow planning.
- [x] S2C `ThoughtBatch` (full on tab open, incremental at 4 Hz with a
      per-bot high-water mark); **Mind tab** renders newest-first — nothing
      auto-scrolls, ever (standing rule)
- [ ] Directive history + replay scrubber (the ring buffer IS the history;
      scrubber UI deferred)
- [x] Inbox: `EscalationStore` (pending + consumed responses, version-bumped),
      HTTP POST/GET/DELETE `/telemetry/escalation`, S2C `InboxState`
      (on subscribe + on version change), C2S `InboxRespond`, overlay Inbox
      tab with badge count, option buttons, free-text ruling, →L5, dismiss
- [x] Agent `escalation.ask()` — posts, BLOCKS on the ruling, withdraws on
      timeout so the inbox never holds dead questions; AFK degrades to the
      pre-L4 behavior, never to a wedged fleet
- [x] Triggers wired (2 of 5): **`ASK_PLAYER`** (dispatch intercept; ruling
      returns in result text as "player says: …") and **ambiguous_item**
      (l2-mcp candidates → inbox options; ruling replaces the guess).
      **All five now wired**: attempts exhausted (options replan / skip /
      abort; free text becomes replan guidance via subtask.error → EXC
      prompt), impossible criteria (player may veto the evidence-gated
      goalpost move; timeout accepts, the old behavior), directive timeout
      (one 5-minute extension grantable; second expiry cancels
      unconditionally).
- [x] Responses: choose / answer / escalate_l5 / cancel
- [x] L5 path: `l5.consult()` (OpenAI, only if OPENAI_API_KEY is set) — the
      suggestion returns **to the inbox** as an `l5_review` item requiring
      approval; nothing from L5 travels down the chain unreviewed
- [x] `ASK_PLAYER` in L3 vocabulary, l2-mcp KNOWN_KINDS, mc_items passthrough

**Provable:** ask a bot for an ambiguous item, get a ruling request, resolve
it, watch the corrected directive run.

## Phase 4 — Talk

- [x] `TalkStore` (mod): pending queue + 30-line per-bot transcript;
      `/telemetry/talk` POST (enqueue — C2S handler AND web dashboard share
      it), `/telemetry/talk/reply` (agent), GET poll/history
- [x] Agent talk worker: polls, answers with `l3_planner.converse()` —
      single conversational call carrying persona (`_BOT_VOICES`), world
      state, and the current directive line. No JSON, no plan, temp 0.7.
- [x] C2S `TalkSend`/`RequestTalk`, S2C `TalkHistory` (full, tiny, resent on
      change); exchanges also echo into the Mind stream
- [x] Talk sub-tab: chat-style tail-anchored transcript, Enter or Send;
      the Order/Talk split is structural — Talk tab = conversation lane,
      game chat = order lane
- [ ] **In-game proof**: ask Scout what it makes of the terrain; no plan

**Provable:** ask Scout what it makes of the terrain; no plan is created.

## Phase 5 — jack in (husk design; cross-dimension is the intent)

- [x] Husk: `HuskPlayer` at the player's exact position wearing their skin
      (profile textures copied), carrying their health/food; no brain, no
      self-defense. **Inserted as a REAL level entity via `addNewPlayer`** —
      unlike the bots' packet ghosts — so mobs can target it AND it counts
      for mob spawning: an abandoned body makes the night dangerous.
- [x] Real player → SPECTATOR → vanilla `setCamera(bot)` (cross-dimension
      teleport + chunk streaming for free); camera re-asserted 10 ticks later
      so the client has the bot entity after a dimension switch; gamemode
      restored on eject
- [x] Damage mirroring husk → player health bar live, with an actionbar
      warning; **husk death = snap back into the dying body and die there**
      (drops at the body site); no auto-eject on damage
- [x] Eject returns the player to the husk position/rotation; force-eject on
      logout (before entity save), bot death/despawn ("the link collapses"),
      husk death, and server stopping
- [x] The tether: `JackState` at 4 Hz to jacked players (overlay open or
      not) + always-on HUD line — bot name, body hearts (color-coded),
      body position/dimension, "H → eject"
- [x] ◈ Jack in / ⏏ Eject buttons on the unit Status tab
- [x] Overlay, Command, and Talk all work while jacked in (H opens the
      overlay in spectator)
- [x] **First live jack-in (2026-08-10): crashed the server — root-caused
      and fixed.** The husk ticked as a real player, and rctmod's
      player-tick hook NPE'd on its missing login state (`PlayerState.get`
      → null → server-thread crash, 4s after jack-in). Fixes: (1) the husk
      no longer ticks — everything it exists for (mob targeting, hurt,
      death, damage mirroring) is push-based and survives; (2) each session
      tick is exception-isolated — a husk problem force-ejects the session,
      never the server; (3) camera re-asserts every second while jacked
      (the one-shot re-assert lost the race with chunk loading — player saw
      the bot's face from inside its hitbox). **The safety net held during
      the crash**: eject-all fired on shutdown, player restored to their
      body's position and gamemode before the save.
- [x] **Second live jack-in (2026-08-10): crashed the server — root-caused
      and fixed.** Same missing rctmod state, different tick: a TrainerMob's
      targeting scan (`updateTarget → getNearbyPlayers`) tested its predicate
      against the husk in `level.players()` and NPE'd in the *trainer's* tick
      — no husk-side override can protect someone else's tick. Real fix: the
      husk **announces itself as a login** — `PlayerLoggedInEvent` posted on
      spawn, `PlayerLoggedOutEvent` on removal — so all 327 mods initialize
      (and release) per-player state through the same path a real join uses;
      packet sends to it die safely in `BotPacketListener`. A handler that
      throws during login aborts the jack-in loudly instead of crashing
      later. Verified live: rctmod logged "Registered trainer player:
      Tiller_hsk" and a probe husk soaked in the level next to the base
      without incident.
- [x] Headless husk regression probe (`diag: husk_in`/`husk_out`) — a bot is
      a ServerPlayer, so it can jack into another bot through the real path,
      parking a real husk in `level.players()` without risking a player.
      Known artifact: the spectator switch throws on fake players (absent
      from chunk-tracking maps) *after* the husk spawns — fine for the
      probe's purpose. Temporary; remove with SpikeDiagnostics.
- [ ] **In-game re-test** (player): jack in, confirm the camera binds,
      take husk damage, eject

## Phase 6 — the logistics fabric

Gated on Phase 0 findings.

- [x] `WirelessME` — grid via the worn terminal (inventory or curio slot);
      power honored per operation; range a config knob defaulting to
      unlimited (`AIPLAYER_ME_HONOR_RANGE`); every failure is an honest
      status ("no terminal", "unpowered", "unlinked"), never an exception
- [x] `MEStoreBehavior`/`MEWithdrawBehavior` prefer the worn terminal
      (instant, network-wide, no walking), fall back to the interface scan
- [x] API: `me_status` (now with grid diagnostics — nodes, machines, stored
      power), `me_search`, `me_push`, `me_pull`; agent helpers added
- [x] Overlay Vault tab is the fabric console: carried / vault / **ME**
      columns, network-wide search when a terminal is online, ⇊ ME→bot /
      ⇈ bot→ME buttons, offline reason shown in place of the buttons
- [ ] Curios equip action + curios row in the overlay (terminal works from a
      plain inventory slot — the curio slot is ergonomics, deferred)
- [x] **Proven against the REAL network** (2026-08-10): terminal linked to
      the player's overworld access point programmatically; grid = 4,826
      nodes, 1.65M AE; 64 netherrack pushed in the overworld, Scout pulled
      them back from the Nether; net zero on player storage. (The earlier
      synthetic `/setblock` rig never formed a grid — command-placed AE2
      machines do not connect; AE2 test rigs must be player-built.)
- [ ] `me_search` re-verify against the live grid (fix deployed — public-type
      reflection — but the AP currently sits on a fragmented 1-node grid
      when the player is away; verify next time they are at the base)

**Provable:** a bot in the Nether pulls certus quartz from the overworld ME
network. **MET** (netherrack variant, see above).

## Phase 7 — polish to feature-complete (nothing deferred)

The player's ruling: the bot interface finishes entirely before the
inventory/menu-directive feature (v8) starts. Every formerly-deferred item
is in scope. Everything here also transfers to the hive mod overlay.

### 7a. Honesty and hygiene (server↔client contract)

- [ ] Bandwidth discipline: `FleetSnapshot` and `JackState` are diff-gated —
      the server remembers the last payload sent per subscriber and skips
      the send when nothing changed (thoughts/inbox/talk are already
      high-water-mark / version / dirty gated). 4 Hz stays the *ceiling*,
      not the floor.
- [ ] Agent-down visibility: the mod stamps every agent contact (any
      `/telemetry/*` poll or push); `FleetSnapshot` carries
      `agentSecondsAgo`; the overlay shows a red "⚠ agent silent Ns" banner
      on Fleet and unit tabs past 15 s. No more "directives vanish into a
      dead agent" mysteries.
- [ ] Hive seam: every per-bot payload carries the bot's stable UUID
      (`id`) alongside the display name; server handlers resolve by id
      first, name as fallback; client caches key by id. The packet schema
      never assumes a single owner even though only one exists today.

### 7b. Curios (closes the Phase 6 gap)

- [ ] `curios_equip` / `curios_unequip` API actions — reflective
      `CuriosApi`, first matching slot wins on equip, honest statuses
      ("no curios slot accepts <item>", "slot occupied" + what's in it)
- [ ] `VaultSnapshot` grows a curios section (slot id, item, name); the
      Vault tab renders a **Worn** row group with equip/unequip buttons —
      the portable-terminal loadout is visible and editable from the
      overlay
- [ ] EQUIP_ALL considers curio-typed items (terminal, rings, belts) so
      "equip the armor" in v8 covers the whole loadout

### 7c. Command surface (also the v8 entry point)

- [ ] Schema push: the agent POSTs its directive schemas
      (`agent/dashboard/schemas.py`, JSON) to `/telemetry/schemas` at
      startup; the mod stores and relays to subscribed clients once per
      version
- [ ] Directive builder: a **Command** sub-tab on each unit renders the
      schema as a form (kind picker → typed param fields with hints);
      submit enqueues an order
- [ ] Order queue: `/telemetry/orders` mirrors the talk-store pattern
      (pending per bot, agent polls, acks); an order routes through
      `plan_orchestrator.execute_task` — the SAME path as chat orders, so
      all five L4 escalation triggers ride along for free. This queue is
      exactly where v8's inventory orders will enter.
- [ ] Crosshair targeting: "⌖" beside x/y/z param fields fills them from
      the client's current look-at block (client `hitResult`, no overlay
      close, no server round-trip)
- [ ] Confirmation on destructive orders: two-step confirm (same button
      re-armed red for 3 s) on interrupt, channel-commit-with-interrupt,
      and ME-push-all. No modals.

### 7d. Memory and matter (the two big UX pieces)

- [ ] Mind tab replay scrubber: pause freezes the stream; a timeline
      slider scrubs the client-held ring buffer (100 thoughts/bot);
      unpause returns to live. Newest-first stays; no autoscroll, ever.
- [ ] Vault transfer fabric: `VaultOp` grows cross-target moves —
      player inventory ↔ bot carried, player ↔ bot vault, bot vault →
      another bot's vault. UI: selecting an item in the Vault tab reveals
      a "send to…" strip (player / each living bot); server validates
      liveness + capacity and reports honest partials ("sent 32/64,
      Forge's pack is full").

### 7d½. Hardening found by the verification itself (2026-08-10)

- [x] **`POST /bot/{name}/inventory` and `give` were booby traps**: both
      NPE'd inside the server-thread lambda on a malformed body, leaving
      `future.join()` — and one HTTP pool thread of four — wedged forever.
      Worse, the inventory endpoint clears the bot's inventory BEFORE the
      NPE: a bad body destroyed Scout's carried items (terminal included)
      during headless verification. Both endpoints now 400 on malformed
      bodies before touching the bot, and their lambdas complete
      exceptionally instead of hanging the pool. Scout's inventory restored
      (terminal re-given, re-linked, re-charged + 84 netherrack).
- [x] `POST /telemetry/orders` without a `status` field is a SUBMISSION —
      dashboard/headless parity with the overlay's SubmitOrder packet.
- [x] Agent schema push is a keeper loop, not a one-shot: the mod's
      SchemaStore is in-memory and empties on every server restart, and a
      modded boot outlasts any fixed retry budget.

### 7d¾. Live-session findings (2026-08-10 night, player in-game)

- [x] **Phantom bots**: spawn packets were broadcast dimension-blind, so a
      bot in the End rendered as a copy at the same coordinates in every
      player's world — the player fought a phantom Mystic for half an hour
      (orders "failing" against a bot that was really in the End all
      along, teleport-to-where-it-already-was loops re-painting the
      phantom). Broadcasts are now dimension-aware; players get bot
      re-syncs on dimension change; stale copies are actively removed.
- [x] Teleport criteria tolerance: safe-ground Y adjustment blew the old
      Manhattan≤3 gate; now horizontal≤4 and vertical≤6 separately.
- [x] Instant-complete directives (teleport already at target) confirmed
      against the mod's last-completed record instead of "never appeared".
- [x] NO LINK: keepalive floor (5 s) sat above the client's 3 s staleness
      threshold; now 2 s.
- [x] Refusals are loud: jack-in refusal → chat + server log; acks render
      as HUD toast when the overlay is closed.
- [x] Vault totals push on action completion (five channel commits
      executed invisibly — XP paid, pane stale).
- [x] Cmd tab dropdowns (directive kinds, option params, CHANNEL item
      catalog injected by the agent from /transmute/names).
- [x] Click-to-expand full text on Talk lines, Mind thoughts, and inbox
      questions; inbox questions word-wrap (truncated errors are useless).
- [x] **Free-look while jacked**: vanilla spectate copies the bot's head
      rotation (pathfinding stares at the ground); a client camera-angle
      override gives the traveler their own mouse-driven view from the
      bot's eyes.
- [x] SFM slot pools synchronized (static unsynchronized ObjectPools —
      the true source of the "already freed slot" flood + FATALs under
      our parallel executor).

### 7e. Verification gate (blocks v8 start)

- [x] Headless (2026-08-10): schemas at version 1 (10,517 chars, 21 kinds);
      order o1 (GOTO) submitted via HTTP → agent drained → execute_task →
      L1 dispatch accepted → criteria verified → plan complete;
      `curios_equip` put the wireless terminal in Scout's
      `adv_pattern_encoder` curio slot and `me_status` resolved the FULL
      grid (4,826 nodes) through it; **`me_search` verified against the
      live network** (netherrack count exact, 50-item page on empty query)
      — the fastutil-accessibility fix is confirmed, and the earlier
      emptiness was grid fragmentation, as diagnosed.
- [ ] In-game (player checklist): camera binds on jack-in; E opens the
      overlay while jacked; interrupt a MINE → channel 32 quartz → resume;
      ask Scout a terrain question over Talk (no plan created); build and
      submit a directive from the Command tab; drag an item Scout → Forge;
      `me_search` at the base returns the live grid
- [ ] Cleanup after the in-game pass: delete `SpikeDiagnostics`, the
      `diag` API case (incl. husk probes), and this line

## Cross-cutting

- [x] Bandwidth discipline, destructive-order confirmation, agent-down
      visibility, and hive-seam ids — all promoted into Phase 7 (above)
      by the player's "nothing deferred" ruling.

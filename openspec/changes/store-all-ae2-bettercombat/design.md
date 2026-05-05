## Context

The mod currently has 20 behavior state machines driven by the `DirectiveType` enum. Container operations (`CONTAINER_STORE`, `CONTAINER_WITHDRAW`, `CONTAINER_SEARCH`, `CONTAINER_PLACE`) handle single-item types via the `ContainerRegistry`. Combat uses `CombatBehavior` with direct damage and vanilla swing animations. No mod compat layer exists yet.

The server runs AE2 for endgame storage and Better Combat for melee animations. Bots are disconnected from both systems — they can't deposit into ME networks and their swings look wrong compared to real players using Better Combat weapons.

## Goals / Non-Goals

**Goals:**
- Bots can dump their entire inventory in one directive (`STORE_ALL`)
- Bots can store/retrieve items from AE2 ME Interface blocks when AE2 is present
- Bot attack animations match Better Combat's weapon-specific swings when that mod is present
- All compat is soft — mod compiles and runs cleanly without AE2 or Better Combat

**Non-Goals:**
- No portable terminal / ME crafting / autocrafting requests
- No import/export bus interaction (block-level automation, not player actions)
- No AE2 channel management or network building
- No Better Combat combo chains or special attacks — just the base swing animation
- No new agent planner logic in this change (agent just gains new directive types to issue)

## Decisions

### 1. Store All: Reuse ContainerRegistry, iterate item types

**Decision**: `StoreAllBehavior` iterates the bot's inventory, groups stacks by item, and delegates storage per-type using the same container-finding logic as `ContainerStoreBehavior`.

**Why not just loop ContainerStoreBehavior**: A meta-behavior would require managing multiple child behavior lifecycles. Simpler to inline the deposit loop since the pathing is trivial (bots teleport to containers).

**Filtering**: Skip items in hotbar slot 0 (equipped weapon), armor slots, and any item with `FoodProperties`. Configurable via `extra` params: `keep_food=true` (default), `keep_tools=true` (default).

### 2. AE2: Access via IItemHandler capability on ME Interface block entities

**Decision**: Use NeoForge's capability system (`level.getCapability(Capabilities.ItemHandler.BLOCK, pos, direction)`) to get `IItemHandler` from ME Interface blocks. This is AE2's public API contract for external item insertion/extraction.

**Alternatives considered**:
- Direct AE2 `IStorageService` API — more powerful but requires compile-time AE2 dependency with API access. IItemHandler is the stable public interface.
- AE2's `ICraftingService` — out of scope (crafting requests are a non-goal).

**Why IItemHandler**: It handles oversized stacks transparently (Extended AE2 interfaces implement the same capability), requires no AE2-specific imports at runtime (just NeoForge capabilities), and is the intended external mod interaction point.

**Discovery**: Bots find ME Interfaces by scanning nearby block entities within a configurable radius (default 16) for the ItemHandler capability. No persistent registry needed — AE2 networks are dynamic.

### 3. AE2: Compat package with classloading isolation

**Decision**: All AE2-specific code lives in `com.sigmastrain.aiplayermod.compat.ae2`. The main behavior classes (`MEStoreBehavior`, `MEWithdrawBehavior`) only reference NeoForge capability APIs, never AE2 classes directly. A `AE2Compat` helper class handles detection.

**Why**: If AE2 classes are referenced in a class that gets loaded without AE2 present, you get `NoClassDefFoundError`. By keeping all code in NeoForge-native APIs (capabilities), we avoid this entirely. The mod-detection gate is just for feature availability, not classloading safety.

### 4. Better Combat: Intercept at animation broadcast point

**Decision**: In `CombatBehavior`, replace the vanilla `ClientboundAnimatePacket.SWING_MAIN_HAND` with Better Combat's animation packet when the mod is loaded. Better Combat registers custom weapon animations via its data pack system — we read the weapon's attack animation ID and broadcast the corresponding packet.

**Alternatives considered**:
- Calling Better Combat's player attack method — would require the bot to go through BC's full attack pipeline. Too coupled.
- Sending both vanilla + BC packets — redundant, BC clients ignore vanilla swings for BC-registered weapons.

**Approach**: `BetterCombatCompat` class checks if the held weapon has a BC animation registered (via `WeaponRegistry`), builds the attack animation packet, and broadcasts it. Falls back to vanilla swing for non-BC weapons.

### 5. Directive types: Flat enum additions

**Decision**: Add `STORE_ALL`, `ME_STORE`, `ME_WITHDRAW` to `DirectiveType`. ME directives fail immediately with a clear message if AE2 is not loaded.

**Why not a sub-enum or namespace**: The existing pattern is flat — 20 types already. Three more is fine. The agent already handles directive types as strings.

## Risks / Trade-offs

- **[AE2 version coupling]** → AE2's `IItemHandler` on ME Interfaces is stable across versions, but if they change the block entity class hierarchy, capability lookup could break. Mitigation: wrap in try-catch, degrade gracefully with a log warning.
- **[Better Combat packet format]** → BC's network protocol is internal API. Updates could change packet structure. Mitigation: version check on mod metadata; disable compat if version is unexpected.
- **[Store All performance]** → A bot with 36 diverse item types hitting full containers could scan many containers. Mitigation: cap at 10 container scans per tick, spread across multiple ticks.
- **[ME Interface discovery radius]** → Scanning block entities in a radius every directive start is O(n) on loaded chunks. Mitigation: 16-block radius is small (at most ~4096 blocks), and it's a one-time scan at directive start, not per-tick.

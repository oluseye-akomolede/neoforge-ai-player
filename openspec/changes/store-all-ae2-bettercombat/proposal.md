## Why

Bots currently store items one type at a time, have no access to AE2 ME networks (the dominant endgame storage system in modded play), and their combat animations don't match the Better Combat mod installed on the server. These gaps make bots feel disconnected from the modded ecosystem during endgame play.

## What Changes

- **Store All directive**: New `STORE_ALL` behavior that dumps all non-essential inventory items (skipping equipped weapon, armor, and food) into nearby registered containers in one operation.
- **AE2 ME storage integration**: Soft-dependency on Applied Energistics 2. When AE2 is loaded, bots can store and retrieve items from ME Interface blocks (including oversized/extended interfaces). New `ME_STORE` and `ME_WITHDRAW` directive types gated behind runtime mod detection.
- **Better Combat animation integration**: Soft-dependency on Better Combat. When loaded, bot attack swings use Better Combat's weapon-specific animation packets instead of vanilla `SWING_MAIN_HAND`, making bot combat visually consistent with player combat.

## Capabilities

### New Capabilities
- `store-all`: Bulk inventory dump behavior — stores all non-essential items across available containers
- `ae2-storage`: ME network store/withdraw operations via ME Interface block entities, gated behind AE2 presence
- `better-combat-compat`: Better Combat animation dispatch for bot attacks, gated behind mod presence

### Modified Capabilities
- `bot-behaviors`: Adding three new behavior state machines (StoreAllBehavior, MEStoreBehavior, MEWithdrawBehavior) and modifying CombatBehavior's animation dispatch
- `bot-inventory`: ME storage extends the "where items can go" contract — bots can now target ME network as a storage destination

## Impact

- **Code**: New `compat/ae2/` and `compat/bettercombat/` packages. New `StoreAllBehavior`. Modified `DirectiveType` enum, `BotBrain.createBehavior()`, `CombatBehavior`, `HttpApiServer`.
- **Dependencies**: AE2 added as `compileOnly` (optional). Better Combat added as `compileOnly` (optional). Both declared as optional in `neoforge.mods.toml`.
- **API**: New directive types `STORE_ALL`, `ME_STORE`, `ME_WITHDRAW`. New API endpoints or existing directive endpoint accepts new types.
- **Serialization**: Store All has no serialization impact (uses existing container registry). AE2 integration adds ME Interface block positions to container-adjacent state but doesn't affect bot serialization format. Better Combat is purely visual — no state impact.
- **Agent**: Python agent planner needs awareness of new directive types for L2/L3 planning.

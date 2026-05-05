## 1. Foundation — Directive Types & Compat Infrastructure

- [x] 1.1 Add `STORE_ALL`, `ME_STORE`, `ME_WITHDRAW` to `DirectiveType` enum
- [x] 1.2 Wire new types in `BotBrain.createBehavior()` switch statement
- [x] 1.3 Create `com.sigmastrain.aiplayermod.compat` package with `ModCompat` utility class (wraps `ModList.get().isLoaded()` checks for `ae2` and `bettercombat`)
- [x] 1.4 Add AE2 as `compileOnly` dependency in `build.gradle` and optional dependency in `neoforge.mods.toml`
- [x] 1.5 Add Better Combat as `compileOnly` dependency in `build.gradle` and optional dependency in `neoforge.mods.toml`

## 2. Store All Behavior

- [x] 2.1 Create `StoreAllBehavior` implementing `Behavior` with phases: VALIDATE → SCAN_INVENTORY → FIND_CONTAINER → DEPOSITING → NEXT_ITEM → COMPLETE
- [x] 2.2 Implement essential-item filtering logic (selected weapon slot, armor slots, FoodProperties items, custom `keep_items` extra param)
- [x] 2.3 Implement item-type iteration loop — group inventory by item type, deposit each type into nearest container with space
- [x] 2.4 Implement container-full fallback — conjure new container when all registered containers are full (reuse logic from ContainerStoreBehavior)
- [x] 2.5 Add progress reporting and systemChat messages for store-all operations

## 3. AE2 ME Storage Integration

- [x] 3.1 Create `com.sigmastrain.aiplayermod.compat.ae2.AE2Compat` class with `isLoaded()` check and ME Interface discovery logic (scan block entities within radius for IItemHandler capability)
- [x] 3.2 Create `MEStoreBehavior` implementing `Behavior` with phases: VALIDATE → FIND_INTERFACE → INSERTING → COMPLETE
- [x] 3.3 Implement ME insertion via `IItemHandler.insertItem()` — handle single-item and "all" target modes
- [x] 3.4 Create `MEWithdrawBehavior` implementing `Behavior` with phases: VALIDATE → FIND_INTERFACE → EXTRACTING → COMPLETE
- [x] 3.5 Implement ME extraction via `IItemHandler.extractItem()` — scan slots for matching item, extract up to requested count
- [x] 3.6 Add graceful failure when AE2 not loaded (immediate FAILED result with clear reason)
- [x] 3.7 Add progress reporting, systemChat messages, and logging for ME operations

## 4. Better Combat Animation Integration

- [x] 4.1 Create `com.sigmastrain.aiplayermod.compat.bettercombat.BetterCombatCompat` class with `isLoaded()` check
- [x] 4.2 Implement weapon animation lookup — determine if held weapon has a Better Combat animation registered
- [x] 4.3 Implement BC animation packet construction and broadcast to all online players
- [x] 4.4 Modify `CombatBehavior` attack section — delegate animation dispatch to `BetterCombatCompat` when loaded, fall back to vanilla swing otherwise
- [x] 4.5 Add try-catch around BC compat calls with fallback to vanilla swing on any exception

## 5. HTTP API & Agent Integration

- [x] 5.1 Ensure `HttpApiServer` directive endpoint accepts `STORE_ALL`, `ME_STORE`, `ME_WITHDRAW` types (existing directive handler should work — verify type parsing)
- [x] 5.2 Add `/bot/{name}/me-status` endpoint that reports whether AE2 is available and nearest ME Interface position (optional, useful for agent planning)
- [x] 5.3 Update Python agent's directive type list in `api.py` to include new types
- [x] 5.4 Add L2 planner awareness of STORE_ALL as a cleanup step after mining/gathering sequences

## 6. Testing & Validation

- [x] 6.1 Build mod with `./gradlew build` — verify compilation with optional deps not present
- [ ] 6.2 Test STORE_ALL in-game: full inventory → dump → verify only essentials remain
- [ ] 6.3 Test ME_STORE/ME_WITHDRAW in-game with AE2 loaded: verify items flow in/out of ME network
- [ ] 6.4 Test Better Combat animations in-game: verify bot attacks show correct weapon swing
- [ ] 6.5 Test graceful degradation: verify mod works cleanly without AE2 and without Better Combat

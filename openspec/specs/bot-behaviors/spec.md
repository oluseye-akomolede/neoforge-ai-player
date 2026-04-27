# Bot Behaviors Specification

## Purpose
Defines the behavior state machines that execute directives — their phases, timing constants, and observable patterns.

## Requirements

### Requirement: Phase-Based State Machines
Each Behavior MUST be implemented as a phase-based state machine that returns BehaviorResult (RUNNING, SUCCESS, FAILED) on each tick.

#### Scenario: Behavior returns result each tick
- GIVEN a MineBehavior in the "mining" phase
- WHEN the server ticks
- THEN the behavior MUST return RUNNING while mining is in progress
- AND return SUCCESS once all requested blocks have been mined

### Requirement: Channeling Speed
All behaviors that involve meditation or channeling MUST use 5 ticks per XP level (0.25 seconds at 20 TPS).

#### Scenario: Uniform channeling speed
- GIVEN any behavior that needs to meditate for XP
- WHEN it enters its meditation phase
- THEN it gains 1 XP level every 5 ticks

### Requirement: Escalating Search
Behaviors that search for blocks MUST use escalating search radii: 32 → 64 → 128 → 256 → 512 → 1024 blocks. Default starting radius is 256.

#### Scenario: Search radius escalates on failure
- GIVEN a MineBehavior searching for diamond_ore starting at radius 256
- WHEN no diamond_ore is found within 256 blocks
- THEN the search radius MUST escalate to 512 blocks
- AND if still not found, escalate to 1024 blocks before falling back

### Requirement: Ore Variant Matching
MineBehavior MUST handle ore variants by stripping namespaces, extracting the base material name, and matching any block containing both the base name and "ore".

#### Scenario: Slate ore variant matched
- GIVEN a search for "allthemodium_ore"
- WHEN scanning blocks
- THEN "allthemodium:allthemodium_slate_ore" is matched
- AND "allthemodium:deepslate_allthemodium_ore" is also matched

### Requirement: Safe Y Positioning
GotoBehavior and FollowBehavior MUST adjust target Y coordinates upward if the destination is inside a solid block.

#### Scenario: No clipping into terrain
- GIVEN a goto target at (100, 64, 200) where Y=64 is solid stone
- WHEN the bot navigates there
- THEN the target Y is adjusted upward until a non-solid block is found
- AND the bot arrives on top of the surface

### Requirement: Cross-Dimension Follow
FollowBehavior MUST support cross-dimension teleportation when the target is in a different dimension.

#### Scenario: Follow across dimensions
- GIVEN a bot following "Steve" in the overworld
- WHEN Steve enters the nether
- THEN after a search delay (40 ticks), the bot teleports to the nether near Steve

### Requirement: Self-Healing Crafting
CraftBehavior MUST resolve full recipe chains and channel missing ingredients via XP when they cannot be found in inventory or the world.

#### Scenario: Missing crafting ingredient channeled via XP
- GIVEN a CraftBehavior executing a directive to craft a diamond_pickaxe
- WHEN the bot has sticks but no diamonds in inventory and none are findable in the world
- THEN the behavior MUST channel diamonds via XP meditation before proceeding with crafting

### Requirement: Self-Healing Brewing
BrewBehavior MUST resolve potion recipe chains, channel missing ingredients (including water bottles and blaze powder), and find or channel a brewing stand.

#### Scenario: Missing brewing stand channeled
- GIVEN a BrewBehavior executing a directive to brew a healing potion
- WHEN no brewing stand is found within the search radius
- THEN the behavior MUST channel a brewing stand via XP and place it before proceeding

### Requirement: Channeling Fallback
When MineBehavior cannot find the target block after exhausting all search radii, it MUST fall back to channeling the item via XP if it exists in the TransmuteRegistry.

#### Scenario: Mine falls back to channeling
- GIVEN a MineBehavior searching for ancient_debris
- WHEN all search radii up to 1024 have been exhausted with no blocks found
- THEN the behavior MUST fall back to channeling ancient_debris via XP if it exists in the TransmuteRegistry
- AND report the fallback in the progress events

### Requirement: Container Conjuring
ContainerStoreBehavior MUST conjure a new chest (3 XP) when no container with available space exists within search radius.

#### Scenario: Chest conjured when none available
- GIVEN a ContainerStoreBehavior attempting to store 64 cobblestone
- WHEN no container with free space is found within the search radius
- THEN the behavior MUST conjure a new chest at a cost of 3 XP and place it near the bot

### Requirement: Behavior Timing Constants
All behaviors MUST respect the following timing constants:

| Behavior | Constant | Value | Description |
|----------|----------|-------|-------------|
| ChannelBehavior | TICKS_PER_ITEM | 5 | Ticks per item conjured |
| ChannelBehavior | TICKS_PER_LEVEL | 5 | Ticks per meditation level |
| MineBehavior | TICKS_PER_LEVEL | 5 | Ticks per meditation level |
| CraftBehavior | TICKS_PER_LEVEL | 5 | Ticks per meditation level |
| BrewBehavior | CHANNEL_TICKS_PER_LEVEL | 5 | Ticks per meditation level |
| EnchantBehavior | TICKS_PER_LEVEL | 5 | Ticks per meditation level |
| EnchantBehavior | ENCHANT_DURATION | 60 | Ticks for enchanting animation |
| ContainerPlaceBehavior | CHANNEL_TICKS | 5 | Ticks for container conjuring |
| GotoBehavior | MAX_TICKS | 600 | Timeout for navigation |

#### Scenario: Navigation times out
- GIVEN a GotoBehavior navigating to distant coordinates
- WHEN 600 ticks elapse without arriving
- THEN the behavior MUST return FAILED with a timeout reason

### Requirement: Wide Search Behavior
WideSearchBehavior MUST implement a coordinated expanding-cube search across one or more bots. Each bot searches a deterministic X-axis sector of the cube. The behavior MUST support searching for both blocks and entities with fuzzy name matching.

#### Scenario: Single-bot wide search finds a block
- GIVEN a WideSearchBehavior with target "diamond_ore" at center (0, 64, 0)
- WHEN the bot scans expanding shells (32 → 64 → 128 → 256 → 512 → 1024)
- THEN blocks matching "diamond_ore" (including deepslate variants) are detected
- AND the bot navigates to the found block and reports its position

#### Scenario: Multi-bot coordinated search
- GIVEN 3 bots each receive a WIDE_SEARCH directive with the same center and target
- WHEN bot_index=0, 1, 2 and bot_count=3 are specified in the extra params
- THEN each bot searches a distinct 1/3 slice of the X-axis range
- AND no two bots scan the same region

#### Scenario: Fuzzy entity matching
- GIVEN a WideSearchBehavior with search_type=entity and target "cow"
- WHEN scanning entities in the sector
- THEN entities whose type ID or display name contains "cow" are matched
- AND typos within Levenshtein distance of 25% of the query length are tolerated

### Requirement: Wide Search Mapping Data
WideSearchBehavior MUST record notable blocks (ores, containers, spawners) encountered during scanning into the ProgressReport scan data buffer. The agent MUST be able to drain this data via GET /bot/{name}/scan_data to feed it into the terrain database.

#### Scenario: Ores discovered during search
- GIVEN a WideSearchBehavior scanning for "ancient_debris"
- WHEN iron_ore and diamond_ore blocks are encountered during the scan
- THEN those blocks are recorded in the progress report scan data
- AND the agent can poll /bot/{name}/scan_data to retrieve and store them

### Requirement: Wide Search Tick Safety
All world reads in WideSearchBehavior MUST execute on the server tick thread. The behavior runs inside BotBrain.tick() which is called from ServerTickEvent.Post, ensuring tick safety. The per-tick scan budget MUST be capped to prevent tick overruns.

#### Scenario: Scan budget prevents lag
- GIVEN a WideSearchBehavior scanning a large area
- WHEN the scan loop runs on a server tick
- THEN at most 2048 blocks are checked per tick
- AND the server tick rate is not degraded

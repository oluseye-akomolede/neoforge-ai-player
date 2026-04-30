# Bot XP Economy Specification

## Purpose
Defines the XP-based economy system where bots earn, spend, and track experience points as a universal currency for item materialization, enchanting, brewing, and container placement.

## Requirements

### Requirement: XP State
Each bot MUST track XP as two values: experience level (integer) and experience points within the current level (float progress).

#### Scenario: Initial XP grant
- GIVEN a newly spawned bot
- WHEN it first enters the world
- THEN it starts with 10,000 XP points (approximately 53 levels)

### Requirement: XP Earning — Meditation
Bots MUST be able to earn XP through meditation at a rate of 1 level per 2 ticks (0.1 seconds at 20 TPS).

#### Scenario: Meditation for XP
- GIVEN a bot with 10 XP levels
- WHEN it meditates for 50 ticks
- THEN it gains 10 additional levels (total: 20)
- AND enchanting glyph particles are displayed during meditation

### Requirement: XP Earning — Vanilla Sources
Bots MUST earn XP from standard Minecraft sources: mob kills, mining, crafting, and smelting.

#### Scenario: XP earned from mob kill
- GIVEN a bot with 10 XP levels
- WHEN it kills a zombie that yields 5 XP orbs
- THEN the bot's XP increases by the orb value

### Requirement: XP Spending — Channeling
Bots MUST be able to spend XP to materialize items from the TransmuteRegistry at 1 tick per item (near-instant).

#### Scenario: Conjure items via XP
- GIVEN a bot with 15 XP levels
- WHEN it channels 1x diamond (cost: 15 levels)
- THEN 15 levels are deducted and 1 diamond appears in inventory
- AND portal + end rod particles are displayed

### Requirement: XP Spending — Enchanting
Bots MUST be able to spend XP to enchant items. Cost equals the enchant level used (1-30).

#### Scenario: Enchant item via XP
- GIVEN a bot with 30 XP levels and a diamond sword in inventory
- WHEN it enchants the sword at level 20
- THEN 20 XP levels are deducted and the sword receives an enchantment

### Requirement: XP Spending — Container Placement
Bots MUST spend 3 XP levels to conjure a container (chest).

#### Scenario: Conjure a chest via XP
- GIVEN a bot with 5 XP levels
- WHEN it conjures a chest
- THEN 3 XP levels are deducted and a chest is placed in the world

### Requirement: TransmuteRegistry
The server MUST maintain a shared registry mapping item IDs to XP costs.

#### Scenario: Auto-discovery
- GIVEN a bot scans its inventory (4 slots per tick)
- WHEN it encounters an item not in the registry
- THEN the item is added with a heuristic cost based on rarity, stack size, and durability
- AND the registry persists to `aiplayermod-transmute.json` every 600 ticks

### Requirement: TransmuteRegistry Cost Heuristics
XP costs MUST be calculated using item rarity tiers:

| Tier | Vanilla Cost | Modded Cost |
|------|-------------|-------------|
| Common | 2 | 3 |
| Uncommon | 5 | 8 |
| Rare | 10 | 15 |
| Epic | 20 | 30 |

Costs are further adjusted by max stack size, durability, and food status (food items halved).

#### Scenario: Common item cost calculation
- GIVEN an item with Common rarity and vanilla origin
- WHEN its XP cost is calculated
- THEN the base cost is 2 XP levels
- AND the cost is further adjusted by stack size, durability, and food status

### Requirement: EnchantmentRegistry
The server MUST maintain a shared enchantment registry mapping enchantment IDs to max levels and XP costs, following the same pattern as TransmuteRegistry.

#### Scenario: Auto-seeding at startup
- GIVEN the server starts with enchantment registry enabled
- WHEN `EnchantmentRegistry.init(server)` is called during server startup
- THEN all vanilla enchantments are discovered from the server's data-driven registry
- AND each enchantment entry includes ID, max level, XP cost per level, and source ("vanilla")

#### Scenario: Discovery from enchanted items
- GIVEN a bot scans its inventory and finds an item with an unknown enchantment
- WHEN `EnchantmentRegistry.discoverFromItem(stack, source)` is called
- THEN the unknown enchantment is added to the registry with source set to "discovered:{source}"
- AND the registry persists to `aiplayermod-enchantments.json`

### Requirement: EnchantmentRegistry Cost Heuristics
XP costs per enchantment level MUST be estimated based on enchantment weight (rarity):

| Weight Range | Cost Per Level |
|-------------|---------------|
| 1 (Treasure) | 10 |
| 2-3 (Rare) | 8 |
| 4-5 (Uncommon) | 5 |
| 6+ (Common) | 3 |

#### Scenario: Rare enchantment cost estimation
- GIVEN an enchantment with weight 2 (e.g., Mending)
- WHEN its XP cost per level is calculated
- THEN the cost is 8 XP per level

### Requirement: EnchantmentRegistry API
The mod MUST expose GET /enchantments returning the full registry with count and per-entry details (id, max_level, xp_cost_per_level, source).

#### Scenario: Agent fetches enchantment registry
- GIVEN the mod API is running with enchantments initialized
- WHEN the agent sends GET /enchantments
- THEN the response contains all known enchantments with their IDs, max levels, costs, and sources
- AND the count field reflects the total number of registered enchantments

### Requirement: XP Serialization
A bot's XP state MUST be serializable as:

| Field | Type | Description |
|-------|------|-------------|
| experience_level | int | Current XP level |
| experience_points | float | Progress toward next level (0.0-1.0) |
| total_experience | int | Total accumulated XP points |

#### Scenario: XP state round-trip serialization
- GIVEN a bot with 20 experience levels and 0.5 progress toward the next level
- WHEN its XP state is serialized and then deserialized
- THEN the restored state has experience_level 20, experience_points 0.5, and the correct total_experience value

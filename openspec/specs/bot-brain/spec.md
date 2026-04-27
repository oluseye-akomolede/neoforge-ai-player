# Bot Brain Specification

## Purpose
Defines the bot's directive-driven brain system — how bots receive, execute, and report on typed commands through behavior state machines.

## Requirements

### Requirement: Directive Processing
The BotBrain MUST process one active directive at a time through a Behavior state machine, ticking once per server tick.

#### Scenario: Directive lifecycle
- GIVEN an idle bot
- WHEN a MINE directive is set via the API
- THEN BotBrain maps MINE to MineBehavior, calls start(), and ticks it each server tick
- AND the directive status transitions: ACTIVE → COMPLETED or FAILED

### Requirement: Directive Types
The system MUST support the following directive types:

| Directive | Behavior | Description |
|-----------|----------|-------------|
| MINE | MineBehavior | Find block → equip tool → path → mine → collect |
| CRAFT | CraftBehavior | Resolve recipe → channel missing → find table → craft |
| SMELT | SmeltBehavior | Place furnace → insert → wait → extract |
| ENCHANT | EnchantBehavior | Channel enchantment by XP tier (basic/mid/max) |
| BREW | BrewBehavior | Resolve recipe → channel ingredients → find stand → brew |
| CHANNEL | ChannelBehavior | Meditate for XP → conjure items |
| FARM | FarmBehavior | Harvest crops → replant |
| BUILD | BuildBehavior | Place blocks in structure patterns |
| COMBAT | CombatBehavior | Target and attack entities within radius |
| FOLLOW | FollowBehavior | Track entity with cross-dimension teleport |
| GOTO | GotoBehavior | Navigate to coordinates with safe Y |
| TELEPORT | TeleportBehavior | Dimension-aware teleportation |
| SEND_ITEM | SendItemBehavior | Transfer items to another player |
| CONTAINER_STORE | ContainerStoreBehavior | Find container → path → deposit |
| CONTAINER_WITHDRAW | ContainerWithdrawBehavior | Find container → path → extract |
| CONTAINER_PLACE | ContainerPlaceBehavior | Conjure and place a container |
| CONTAINER_SEARCH | ContainerSearchBehavior | Scan containers for items |
| WIDE_SEARCH | WideSearchBehavior | Expanding-cube coordinated search with checkerboard grid |
| IDLE | IdleBehavior | Default state, always returns RUNNING |

#### Scenario: Directive mapped to correct behavior
- GIVEN a bot with no active directive
- WHEN a CRAFT directive is submitted via the API
- THEN BotBrain MUST instantiate CraftBehavior to handle the directive
- AND the directive status is set to ACTIVE

### Requirement: Directive Data
A Directive MUST carry the following fields:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| type | DirectiveType | yes | Enum value from the table above |
| target | string | no | Item/entity/block ID |
| count | int | no | Quantity (default varies by type) |
| radius | int | no | Search radius in blocks (default: 256) |
| x, y, z | double | no | Target coordinates |
| extra | map<string,string> | no | Type-specific parameters |
| status | enum | yes | ACTIVE, COMPLETED, FAILED, CANCELLED |
| failureReason | string | no | Populated on FAILED |

#### Scenario: Directive carries required fields
- GIVEN an API request to mine 64 iron_ore
- WHEN the directive is created
- THEN it MUST contain type=MINE, target="iron_ore", count=64, and status=ACTIVE
- AND optional fields not provided default to null or their type-specific defaults

### Requirement: Self-Preservation
SelfPreservation MUST run before any behavior each tick:
- Flee: Health < 4.0 HP AND hostile within 8 blocks → run opposite direction
- Eat: Food < 14 OR health < max-2 → consume highest-nutrition food, 40-tick cooldown

#### Scenario: Bot flees when low health near hostile
- GIVEN a bot with 3.0 HP and a zombie within 8 blocks
- WHEN the self-preservation check runs before the behavior tick
- THEN the bot MUST flee in the opposite direction from the hostile mob
- AND normal behavior ticking is deferred until the bot is safe

#### Scenario: Bot eats when hungry
- GIVEN a bot with food level below 14 and cooked beef in inventory
- WHEN the self-preservation check runs
- THEN the bot MUST consume the cooked beef
- AND a 40-tick cooldown is applied before the next eat action

### Requirement: Behavior Progress Reporting
Each Behavior MUST report progress via ProgressReport containing:

| Field | Type | Description |
|-------|------|-------------|
| phase | string | Current phase name (lowercase) |
| counters | map<string,int> | Named numeric counters (items_mined, xp_levels_gained, etc.) |
| events | list<string> | Ordered log of significant events |

#### Scenario: Progress reported during mining
- GIVEN a bot executing MINE for 64 iron_ore
- WHEN 32 have been mined
- THEN progress shows phase="mining", counters={items_mined: 32}, events=["Found iron_ore at ...", "Mining..."]

### Requirement: Brain State Serialization
The brain's current state MUST be serializable as:

| Field | Type | Description |
|-------|------|-------------|
| active_directive | Directive | Current directive (null if idle) |
| last_directive | Directive | Most recently completed directive |
| behavior_phase | string | Current behavior phase |
| progress | ProgressReport | Current progress snapshot |

#### Scenario: Brain state serialized while mining
- GIVEN a bot actively executing a MINE directive for iron_ore
- WHEN the brain state is serialized
- THEN the output MUST include active_directive with type=MINE, behavior_phase with the current phase, and a progress snapshot with counters and events

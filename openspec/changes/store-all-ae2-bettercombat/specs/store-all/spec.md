## ADDED Requirements

### Requirement: Store All Directive
The system SHALL provide a `STORE_ALL` directive type that stores all non-essential items from a bot's inventory into available containers in one operation.

#### Scenario: Store all with default filtering
- **WHEN** a bot receives a `STORE_ALL` directive with no extra params
- **THEN** all items EXCEPT the equipped weapon (hotbar slot 0), armor slots, and food items SHALL be deposited into registered containers
- **AND** the behavior reports total items stored on completion

#### Scenario: Store all with custom keep list
- **WHEN** a bot receives a `STORE_ALL` directive with extra param `keep_items=diamond_sword,golden_apple`
- **THEN** items matching those IDs SHALL be retained in inventory in addition to the default exclusions

#### Scenario: Store all with no containers available
- **WHEN** a bot receives a `STORE_ALL` directive and no registered containers have space
- **THEN** the bot SHALL conjure a new container (same as ContainerStoreBehavior) and deposit into it

### Requirement: Store All Item Iteration
The behavior SHALL iterate all occupied inventory slots, group items by type, and deposit each type into the nearest container with available space.

#### Scenario: Multiple item types across containers
- **WHEN** a bot has cobblestone, iron_ingot, and dirt in inventory
- **AND** container A has space for cobblestone only, container B has general space
- **THEN** cobblestone goes to container A, iron_ingot and dirt go to container B

#### Scenario: Partial storage on full containers
- **WHEN** all containers become full before all items are stored
- **THEN** the behavior SHALL conjure a new container for remaining items
- **AND** report partial progress before conjuring

### Requirement: Store All Preserves Essential Items
The behavior SHALL never store items the bot needs for survival and combat.

#### Scenario: Equipped weapon preserved
- **WHEN** a bot has a diamond_sword in hotbar slot 0 (selected slot)
- **THEN** that item SHALL NOT be moved to any container

#### Scenario: Armor preserved
- **WHEN** a bot has armor equipped in armor slots
- **THEN** those items SHALL NOT be moved to any container

#### Scenario: Food preserved by default
- **WHEN** a bot has items with FoodProperties in inventory
- **AND** the directive does not specify `keep_food=false`
- **THEN** food items SHALL NOT be moved to any container

#### Scenario: Food storage when explicitly allowed
- **WHEN** a bot receives `STORE_ALL` with extra param `keep_food=false`
- **THEN** food items SHALL be stored along with other non-essential items

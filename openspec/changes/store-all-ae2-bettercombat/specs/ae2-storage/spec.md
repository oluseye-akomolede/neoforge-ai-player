## ADDED Requirements

### Requirement: AE2 Mod Detection
The system SHALL detect whether Applied Energistics 2 is loaded at runtime and gate all ME storage functionality behind that check.

#### Scenario: AE2 present
- **WHEN** AE2 is loaded (`ModList.get().isLoaded("ae2")` returns true)
- **THEN** `ME_STORE` and `ME_WITHDRAW` directive types SHALL be available

#### Scenario: AE2 absent
- **WHEN** AE2 is not loaded
- **THEN** `ME_STORE` and `ME_WITHDRAW` directives SHALL fail immediately with reason "AE2 not loaded"
- **AND** the mod SHALL load and function normally without AE2 classes

### Requirement: ME Store Directive
The system SHALL provide a `ME_STORE` directive that inserts items from bot inventory into the nearest ME Interface block's network storage.

#### Scenario: Store specific item into ME network
- **WHEN** a bot receives `ME_STORE` with target "minecraft:cobblestone" and count 64
- **AND** an ME Interface block entity exists within 16 blocks
- **THEN** up to 64 cobblestone SHALL be inserted via the block's IItemHandler capability
- **AND** the behavior reports items successfully stored

#### Scenario: Store all into ME network
- **WHEN** a bot receives `ME_STORE` with target "all"
- **THEN** all non-essential inventory items SHALL be inserted into the ME network
- **AND** the same essential-item filtering as STORE_ALL applies

#### Scenario: No ME Interface in range
- **WHEN** a bot receives `ME_STORE` but no block entity with IItemHandler capability exists within search radius
- **THEN** the behavior SHALL fail with reason "No ME Interface found within range"

#### Scenario: ME network full
- **WHEN** the ME network cannot accept more items (IItemHandler returns non-empty remainder)
- **THEN** the behavior SHALL report partial storage and return SUCCESS with the count actually stored

### Requirement: ME Withdraw Directive
The system SHALL provide a `ME_WITHDRAW` directive that extracts items from the nearest ME Interface block's network into bot inventory.

#### Scenario: Withdraw specific item
- **WHEN** a bot receives `ME_WITHDRAW` with target "minecraft:iron_ingot" and count 32
- **AND** an ME Interface block entity exists within 16 blocks with IItemHandler capability
- **THEN** up to 32 iron_ingot SHALL be extracted from the ME network into bot inventory

#### Scenario: Item not in ME network
- **WHEN** a bot requests withdrawal of an item not present in the ME network
- **THEN** the behavior SHALL fail with reason "Item not found in ME network"

#### Scenario: Bot inventory full during withdraw
- **WHEN** the bot's inventory becomes full during withdrawal
- **THEN** the behavior SHALL report partial withdrawal and return SUCCESS with count actually received

### Requirement: ME Interface Discovery
The system SHALL discover ME Interface blocks by scanning nearby block entities for the IItemHandler capability.

#### Scenario: Discovery within default radius
- **WHEN** a ME directive starts
- **THEN** the behavior SHALL scan block entities within 16 blocks of the bot for IItemHandler capability
- **AND** select the nearest qualifying block entity

#### Scenario: Custom search radius via directive
- **WHEN** a ME directive specifies a radius value
- **THEN** that radius SHALL be used instead of the default 16

#### Scenario: Oversized interface stacks
- **WHEN** the ME Interface supports oversized stacks (Extended AE2 addon)
- **THEN** the IItemHandler capability SHALL handle oversized insertions/extractions transparently
- **AND** no special handling is required from the behavior

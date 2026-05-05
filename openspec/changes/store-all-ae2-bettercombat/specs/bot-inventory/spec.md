## ADDED Requirements

### Requirement: ME Network as Storage Destination
A bot's inventory items MAY be stored into or retrieved from an AE2 ME network via ME Interface blocks, extending the available storage destinations beyond physical containers.

#### Scenario: ME store extends storage options
- **WHEN** a bot has items to store and an ME Interface is within range
- **THEN** the ME network SHALL be available as a storage destination alongside registered containers

#### Scenario: ME withdraw extends retrieval options
- **WHEN** a bot needs an item that exists in the ME network
- **THEN** the bot MAY retrieve it via ME_WITHDRAW directive from the nearest ME Interface

### Requirement: Essential Item Classification
The system SHALL classify inventory items as essential or non-essential for bulk storage operations (STORE_ALL, ME_STORE with target "all").

#### Scenario: Default essential items
- **WHEN** no custom keep list is specified
- **THEN** the following are classified as essential: item in selected hotbar slot, items in armor slots, items with FoodProperties

#### Scenario: Custom keep list
- **WHEN** a directive specifies `keep_items` in extra params
- **THEN** those item IDs SHALL also be classified as essential in addition to defaults

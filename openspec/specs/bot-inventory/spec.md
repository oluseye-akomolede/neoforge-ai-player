# Bot Inventory Specification

## Purpose
Defines the bot's item storage systems — the standard player inventory and extended storage.

## Requirements

### Requirement: Standard Player Inventory
Each bot MUST have a standard 36-slot Minecraft player inventory (slots 0-35: 9 hotbar + 27 main) plus 4 armor slots and 1 offhand slot.

#### Scenario: Inventory accessible via API
- GIVEN a bot with items in its inventory
- WHEN the agent calls GET /bot/{name}/inventory
- THEN all occupied slots are returned with item ID, count, slot index, and NBT data

#### Scenario: Inventory manipulation
- GIVEN a bot with an empty inventory
- WHEN items are added via conjuring, mining, or crafting
- THEN items appear in the first available slot respecting stack size limits

### Requirement: Extended Inventory
Each bot MUST have a 54-slot extended inventory accessible via the API for overflow storage.

#### Scenario: Extended inventory overflow
- GIVEN a bot whose standard inventory is full
- WHEN additional items are received
- THEN items MAY be placed in extended inventory slots

### Requirement: Equipment State
A bot's currently equipped items (held item, armor slots, offhand) MUST be tracked and broadcast to nearby players via packets.

#### Scenario: Equipment visibility
- GIVEN a bot equips a diamond sword in its main hand
- WHEN a real player is nearby
- THEN the player sees the bot holding the diamond sword

### Requirement: Item Serialization Format
Each inventory slot MUST be representable as a serializable record containing:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| slot | int | yes | Slot index (0-35 standard, 36-39 armor, 40 offhand, 41-94 extended) |
| item_id | string | yes | Namespaced item ID (e.g., "minecraft:diamond_sword") |
| count | int | yes | Stack count (1 to max stack size) |
| nbt | map | no | NBT tag data (enchantments, custom names, damage, etc.) |

#### Scenario: Enchanted item serialization
- GIVEN a bot holding a diamond sword with Sharpness V
- WHEN the inventory is serialized
- THEN the slot record includes nbt data with the enchantment information

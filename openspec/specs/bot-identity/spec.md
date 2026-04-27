# Bot Identity Specification

## Purpose
Defines the core identity properties of a bot player — the immutable and configurable attributes that distinguish one bot from another.

## Requirements

### Requirement: Unique Name
Each bot MUST have a unique string name that serves as its primary identifier across all systems (mod, agent, dashboard, task board).

#### Scenario: Bot creation with unique name
- GIVEN a request to spawn a bot named "Axiom"
- WHEN no other bot with that name exists
- THEN the bot is created with name "Axiom"
- AND the name is used as the key in BotManager, agent runners, and dashboard state

#### Scenario: Duplicate name rejected
- GIVEN a bot named "Axiom" already exists
- WHEN a request to spawn another "Axiom" arrives
- THEN the request is rejected

### Requirement: Profile Configuration
Each bot MUST have a profile defining its personality, specializations, goals, and behavioral modes.

#### Scenario: Profile loaded at spawn
- GIVEN a profile JSON file for "Axiom" with specializations ["crafting", "mining", "general"]
- WHEN the bot spawns
- THEN the agent loads the profile and uses it for LLM system prompts and task board matching

### Requirement: Profile Properties
A bot profile MUST contain the following properties:

| Property | Type | Description |
|----------|------|-------------|
| name | string | Display name |
| specializations | string[] | Task matching tags (e.g., "mining", "magic", "farming") |
| personality | string | LLM system prompt personality description |
| goals | string[] | High-level behavioral objectives |
| behavioral_modes | map | Boolean flags: self_preservation, self_defense, hunting, item_collecting, torch_placing, cowardice, chatter |

#### Scenario: Behavioral modes affect runtime behavior
- GIVEN a bot with self_preservation=true
- WHEN the bot's health drops below 4 HP with a hostile nearby
- THEN the bot flees instead of continuing its current behavior

### Requirement: Fake ServerPlayer
Each bot MUST be represented as a `BotServerPlayer` (extends `ServerPlayer`) that is NOT added to `level.players()` to avoid mod compatibility crashes.

#### Scenario: Bot invisible to player list iteration
- GIVEN a bot is spawned
- WHEN another mod iterates `level.players()`
- THEN the bot is not included
- AND visibility is handled through manual packet broadcasting

### Requirement: Game Mode and Permissions
A bot MUST operate in survival mode with standard player permissions. Bots MAY have elevated skill levels for mod compatibility (e.g., ProjectMMO integration).

#### Scenario: Bot spawns in survival mode
- GIVEN a bot is being spawned
- WHEN the BotServerPlayer is created
- THEN the bot's game mode is set to survival
- AND the bot has standard player permissions

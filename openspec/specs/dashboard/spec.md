# Dashboard Specification

## Purpose
Defines the React dashboard for real-time monitoring and control of all bots.

## Requirements

### Requirement: Live Bot State
The dashboard MUST display real-time bot state via WebSocket connection with auto-reconnect.

#### Scenario: WebSocket reconnection
- GIVEN the dashboard is open and connected via WebSocket
- WHEN the WebSocket connection drops
- THEN the dashboard MUST automatically attempt to reconnect
- AND bot state updates MUST resume once the connection is restored

### Requirement: Layout
The dashboard MUST present:
- Header: title, online bot count, connection status
- Left panel: world map + bot cards
- Center: command bar + bot detail + event log
- Right: directive panel + data browser

#### Scenario: Dashboard layout rendering
- GIVEN the dashboard is loaded in a browser
- WHEN the page finishes rendering
- THEN the header MUST display the title, online bot count, and connection status
- AND the left panel MUST contain the world map and bot cards
- AND the center panel MUST contain the command bar, bot detail, and event log
- AND the right panel MUST contain the directive panel and data browser

### Requirement: World Map
The WorldMap component MUST render terrain from TerrainDB on a canvas with HTML overlays for bot markers, container icons, waypoint pins, and online player markers.

#### Scenario: Map interaction
- GIVEN the dashboard is connected
- WHEN a user views the world map
- THEN bot positions update in real-time
- AND containers show quick-store/withdraw buttons
- AND waypoints are displayed as pins

### Requirement: Player Markers on Map
Online human players MUST be displayed on the world map as magenta square markers, polled every 5 seconds via GET /api/players. Clicking a player marker shows a tooltip with name, health, gamemode, position, and actions (send bot, teleport bot).

#### Scenario: Player appears on map
- GIVEN a human player is connected to the server
- WHEN the dashboard polls /api/players
- THEN a magenta square marker appears at the player's position on the map
- AND clicking the marker shows a tooltip with goto/teleport actions for the selected bot

#### Scenario: Player dimension filtering
- GIVEN a player is in the nether and the map shows the overworld
- WHEN the user views the overworld map tab
- THEN the nether player marker is NOT shown
- AND switching to the nether tab shows the player marker

### Requirement: Command Bar
Users MUST be able to send natural-language instructions to bots via a text input that routes through the LLM planning pipeline.

#### Scenario: Sending a natural-language command
- GIVEN a bot is selected in the dashboard
- WHEN the user types a natural-language instruction into the command bar and submits it
- THEN the instruction MUST be routed through the LLM planning pipeline
- AND the resulting plan MUST be sent to the selected bot for execution

### Requirement: Directive Panel
Users MUST be able to fire L1 directives directly from dropdown menus with type-specific parameter forms, searchable transmute item picker, searchable enchantment picker, and visual feedback (gold=in-flight, green=success, red=error).

#### Scenario: Firing a directive with visual feedback
- GIVEN the directive panel is visible and a bot is selected
- WHEN the user selects a directive from the dropdown and submits it with parameters
- THEN the directive row MUST display gold coloring while in-flight
- AND the directive row MUST turn green on success or red on error

### Requirement: Enchantment Directive UI
The ENCHANT directive form MUST provide a searchable dropdown populated from GET /api/enchantments (polled every 30 seconds). The dropdown shows each enchantment's ID, max level, XP cost per level, and source badge (vanilla vs. discovered). A level input constrains to 1..max_level. When no specific enchantment is selected, a random tier selector (Basic/Mid/Max) is shown as fallback. The form calculates and displays estimated XP cost.

#### Scenario: Selecting a specific enchantment
- GIVEN the ENCHANT directive is selected
- WHEN the user searches for "sharpness" in the enchantment dropdown
- THEN matching enchantments are filtered and displayed with max level and cost info
- AND selecting "sharpness" sets the enchantment field and constrains the level input to 1-5
- AND the estimated XP cost updates to show (level x cost_per_level)

#### Scenario: Random enchantment fallback
- GIVEN the ENCHANT directive is selected
- WHEN no specific enchantment is chosen
- THEN the form shows a random tier selector with options: Basic (1-8), Mid (9-20), Max (21-30)
- AND the XP cost displays the tier's level cost

### Requirement: Position Picker Buttons
Directive parameters with `use_bot_pos: true` MUST display quick-fill buttons for each bot's current position and each online player's position. Bot buttons use the bot's theme color; player buttons use magenta.

#### Scenario: Fill coordinates from player position
- GIVEN a WIDE_SEARCH directive form is open with x, y, z fields
- WHEN the user clicks a player position button
- THEN the x, y, z fields are populated with the player's current coordinates

### Requirement: Coordinated Search
The directive panel MUST provide a coordinated search section for WIDE_SEARCH directives. Users select multiple bots via checkboxes (with All/None toggles), then click "Search with N bots" to send parallel WIDE_SEARCH directives with correct bot_index and bot_count values.

#### Scenario: Coordinated search across 3 bots
- GIVEN a WIDE_SEARCH directive form is open with target "diamond_ore"
- WHEN the user selects 3 bots and clicks "Search with 3 bots"
- THEN 3 WIDE_SEARCH directives are sent, each with the same target and center
- AND bot_index is 0, 1, 2 respectively and bot_count is 3 for all three

### Requirement: Directive Descriptions and Hints
Each directive type MUST display a description explaining what it does. Individual parameters MUST show hint text explaining their purpose. Dict-type parameters with options MUST render as labeled dropdowns.

#### Scenario: WIDE_SEARCH form shows helpful labels
- GIVEN the WIDE_SEARCH directive is selected
- WHEN the form renders
- THEN the description explains expanding-cube search with parallel bot support
- AND the "Max search radius" dropdown shows labels like "512 blocks (default)"
- AND the search target field shows a hint about fuzzy matching

### Requirement: Data Browser
The data browser MUST provide tabbed views for:

| Tab | Data Source | Features |
|-----|-------------|----------|
| Memories | /api/bots/{name}/memories | Category filtering, decay scores, per-memory delete |
| Tasks | /api/tasks | Status coloring, assignee display |
| Transmute | /api/transmute | Item list with XP costs |
| Enchantments | /api/enchantments | Searchable list with max levels, costs, source badges |
| Containers | /api/containers | Expandable with live contents |
| Waypoints | /api/waypoints | Name, coordinates, dimension |

#### Scenario: Browsing data tabs
- GIVEN the data browser is visible
- WHEN the user selects the Memories tab
- THEN the browser MUST display memories from /api/bots/{name}/memories with category filtering and decay scores
- AND each memory MUST have a delete option

### Requirement: Event Log
The event log MUST display a scrolling stream of agent events with timestamps and color-coded event types. The log MUST NOT auto-scroll — the user controls scroll position.

#### Scenario: Event log scroll behavior
- GIVEN the event log is displaying events
- WHEN new events arrive
- THEN the log MUST NOT auto-scroll to the latest event
- AND the user MUST retain control of the scroll position

### Requirement: Bot Detail
When a bot is selected, the detail panel MUST show full inventory grid, nearby entities with distances, action results, and chat history.

#### Scenario: Viewing bot detail
- GIVEN the dashboard is connected and bots are online
- WHEN the user selects a bot
- THEN the detail panel MUST display the bot's full inventory grid
- AND the detail panel MUST display nearby entities with distances
- AND the detail panel MUST display action results and chat history

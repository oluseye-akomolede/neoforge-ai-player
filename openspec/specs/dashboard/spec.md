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
The WorldMap component MUST render terrain from TerrainDB on a canvas with HTML overlays for bot markers, container icons, and waypoint pins.

#### Scenario: Map interaction
- GIVEN the dashboard is connected
- WHEN a user views the world map
- THEN bot positions update in real-time
- AND containers show quick-store/withdraw buttons
- AND waypoints are displayed as pins

### Requirement: Command Bar
Users MUST be able to send natural-language instructions to bots via a text input that routes through the LLM planning pipeline.

#### Scenario: Sending a natural-language command
- GIVEN a bot is selected in the dashboard
- WHEN the user types a natural-language instruction into the command bar and submits it
- THEN the instruction MUST be routed through the LLM planning pipeline
- AND the resulting plan MUST be sent to the selected bot for execution

### Requirement: Directive Panel
Users MUST be able to fire L1 directives directly from dropdown menus with type-specific parameter forms, searchable transmute item picker, and visual feedback (gold=in-flight, green=success, red=error).

#### Scenario: Firing a directive with visual feedback
- GIVEN the directive panel is visible and a bot is selected
- WHEN the user selects a directive from the dropdown and submits it with parameters
- THEN the directive row MUST display gold coloring while in-flight
- AND the directive row MUST turn green on success or red on error

### Requirement: Data Browser
The data browser MUST provide tabbed views for:

| Tab | Data Source | Features |
|-----|-------------|----------|
| Memories | /api/bots/{name}/memories | Category filtering, decay scores, per-memory delete |
| Tasks | /api/tasks | Status coloring, assignee display |
| Transmute | /api/transmute | Item list with XP costs |
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

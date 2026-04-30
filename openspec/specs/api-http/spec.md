# HTTP API Specification

## Purpose
Defines the mod-side HTTP API that exposes all bot capabilities to the Python agent, and the dashboard REST/WebSocket API.

## Requirements

### Requirement: Mod API Server
The mod MUST expose a REST API on a configurable port (default: 3100) with optional API key authentication.

#### Scenario: Mod API starts on configured port
- GIVEN the mod is loaded with the API port configured to 3100
- WHEN the server starts
- THEN the REST API MUST be listening on port 3100
- AND requests without a valid API key MUST be rejected when authentication is enabled

### Requirement: Mod API Endpoint Categories
The mod MUST expose endpoints across all listed categories to provide full bot control to the Python agent.

| Category | Count | Key Endpoints |
|----------|-------|---------------|
| Bot Lifecycle | 3 | POST /bots, DELETE /bots, GET /bots |
| Observation | 8 | /bot/{name}/status, /inventory, /entities, /blocks, /brain, /xp, /surface_scan |
| Navigation | 4 | /goto, /fly_to, /teleport, /look |
| Combat | 2 | /attack, /combat_mode |
| Mining/Building | 3 | /mine, /place, /find_blocks |
| Crafting | 7 | /craft, /craft_chain, /smelt, /anvil, /smithing, /brew, /enchant |
| XP Economy | 4 | /xp, /meditate, /conjure, /repair |
| Inventory | 7 | /equip, /use, /drop, /collect, /swap, /container*, /send_item |
| Chat | 3 | /chat, /system_chat, /inject_chat |
| Directives | 3 | GET/POST/DELETE /bot/{name}/directive |
| Registries | 8 | /transmute/*, /enchantments, /containers/*, /bot/{name}/nearby_containers |
| Server | 3 | /health, /server/dimensions, /server/players |

#### Scenario: Agent creates a bot via lifecycle endpoint
- GIVEN the mod API is running
- WHEN the agent sends POST /bots with a bot name
- THEN the mod MUST create the bot and return a success response
- AND GET /bots MUST include the newly created bot

### Requirement: Thread Safety
Observation endpoints that read world state MUST be wrapped in `server.execute()` + `CompletableFuture.join()` to run on the main server thread.

#### Scenario: Observation endpoint runs on server thread
- GIVEN the agent requests GET /bot/{name}/status
- WHEN the HTTP handler processes the request
- THEN the world state read MUST execute inside server.execute() on the main server thread
- AND the handler MUST block via CompletableFuture.join() until the result is available

### Requirement: Bot Status Response
GET /bot/{name}/status MUST return:

| Field | Type | Description |
|-------|------|-------------|
| name | string | Bot name |
| health | float | Current HP |
| food | int | Food level |
| x, y, z | double | World position |
| dimension | string | Current dimension (e.g., "minecraft:overworld") |
| gameMode | string | Game mode |
| biome | string | Current biome |
| held_item | string | Main hand item ID |
| xp_level | int | Current XP level |

#### Scenario: Agent retrieves bot status
- GIVEN a bot named Axiom is spawned in the world
- WHEN the agent sends GET /bot/Axiom/status
- THEN the response MUST contain name, health, food, x, y, z, dimension, gameMode, biome, held_item, and xp_level fields

### Requirement: Dashboard API
The dashboard MUST expose a FastAPI server with REST and WebSocket endpoints on a configurable port (default: 5000).

#### Scenario: Dashboard API starts on configured port
- GIVEN the dashboard is configured with port 5000
- WHEN the dashboard process starts
- THEN the FastAPI server MUST be listening on port 5000
- AND both REST and WebSocket endpoints MUST be available

### Requirement: Dashboard WebSocket — State Stream
WebSocket `/ws` MUST push bot state snapshots on every observe tick with version tracking to prevent duplicate sends.

#### Scenario: Dashboard pushes state snapshot to connected client
- GIVEN a client is connected to WebSocket /ws
- WHEN an observe tick fires and the bot state version has changed
- THEN the server MUST push the new state snapshot to the client
- AND if the version has not changed the server MUST skip the send to prevent duplicates

### Requirement: Dashboard WebSocket — Event Stream
WebSocket `/ws/events` MUST stream events from a ring buffer (200 events). Event types:

| Event Type | Description |
|------------|-------------|
| plan_created | LLM plan decomposed |
| step_done | Plan step completed |
| directive_started | L1 directive sent to mod |
| directive_done | L1 directive completed |
| directive_lost | Directive lost to server restart |
| l2_retry | L2 parameter adjustment attempt |
| delegated | Task posted to task board |
| task_claimed | Bot claimed a task |
| container_found | Auto-discovered container |
| command_sent | Dashboard command sent |
| directive_sent | Dashboard directive sent |
| bot_stopped | Bot stopped via dashboard |
| waypoint_set | Waypoint created |
| waypoint_deleted | Waypoint removed |

#### Scenario: Client receives events from ring buffer
- GIVEN a client connects to WebSocket /ws/events
- WHEN a directive_started event is emitted
- THEN the client MUST receive the event with its type and payload
- AND the ring buffer MUST retain up to 200 events

### Requirement: Scan Data Endpoint
GET /bot/{name}/scan_data MUST drain accumulated block scan data from the active behavior's ProgressReport and return it with the current dimension. This enables the agent to feed mapping data into the terrain database.

#### Scenario: Agent drains scan data from wide search
- GIVEN a WideSearchBehavior is running and has recorded 50 notable blocks
- WHEN the agent sends GET /bot/{name}/scan_data
- THEN the response MUST contain the 50 block records with x, y, z, and block_id
- AND the scan data buffer MUST be cleared so subsequent calls return only new data

### Requirement: Enchantment Registry Endpoint
GET /enchantments MUST return the full enchantment registry with count and per-entry details.

#### Scenario: Agent fetches enchantment registry
- GIVEN the mod API is running with EnchantmentRegistry initialized
- WHEN the agent sends GET /enchantments
- THEN the response contains `enchantments` (array of {id, max_level, xp_cost_per_level, source}) and `count` (integer)

### Requirement: Dashboard Enchantments Proxy
The dashboard MUST expose GET /api/enchantments that proxies the mod's /enchantments endpoint, returning the enchantment registry for UI rendering (searchable dropdown in ENCHANT directive form).

#### Scenario: Dashboard fetches enchantment registry
- GIVEN the dashboard is connected to the mod API
- WHEN a client sends GET /api/enchantments
- THEN the response contains the enchantment list from the mod
- AND if the mod API is unreachable, the response returns an empty list with an error message

### Requirement: Dashboard Directive Catalog
The dashboard MUST serve a directive catalog at GET /api/directives listing all 16 available directive types (MINE, CRAFT, SMELT, CHANNEL, ENCHANT, BREW, FOLLOW, GOTO, TELEPORT, COMBAT, FARM, BUILD, SEND_ITEM, WIDE_SEARCH, CONTAINER_PLACE, CONTAINER_STORE, CONTAINER_WITHDRAW) with parameter definitions for UI form generation.

#### Scenario: Dashboard returns directive catalog
- GIVEN the dashboard API is running
- WHEN a client sends GET /api/directives
- THEN the response MUST contain all 16 directive types
- AND each directive entry MUST include parameter definitions for UI form generation

### Requirement: Online Players Endpoint
GET /server/players MUST return a list of online human players (excluding bots). Each entry includes name, position (x, y, z), dimension, gamemode, and health. The handler MUST run on the server thread via CompletableFuture for tick safety.

#### Scenario: Agent fetches online players
- GIVEN two human players are connected and three bots are spawned
- WHEN the agent sends GET /server/players
- THEN the response contains exactly two player entries (bots are filtered out)
- AND each entry includes name, x, y, z, dimension, gamemode, and health

### Requirement: Dashboard Players Proxy
The dashboard MUST expose GET /api/players that proxies the mod's /server/players endpoint, returning player positions for map rendering and coordinate picking.

#### Scenario: Dashboard fetches player positions
- GIVEN the dashboard is connected to the mod API
- WHEN a client sends GET /api/players
- THEN the response contains the same player list as /server/players
- AND if the mod API is unreachable, the response returns an empty list

### Requirement: Dynamic Dimensions
The teleport directive dropdown MUST fetch live dimension names from GET /api/dimensions (proxied from /server/dimensions) with fallback to vanilla three (overworld, nether, end).

#### Scenario: Teleport dropdown fetches live dimensions
- GIVEN the dashboard teleport form is rendered
- WHEN the dropdown requests GET /api/dimensions
- THEN it MUST display the dimension names returned by the mod
- AND if the mod is unreachable it MUST fall back to overworld, nether, and end

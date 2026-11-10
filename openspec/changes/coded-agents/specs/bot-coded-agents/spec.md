## ADDED Requirements

### Requirement: Script Authoring Is LLM-Only
Only the LLM MAY create or modify a bot script. The system MUST NOT expose any
path by which a player or any other client supplies script source.

Players MUST be able to read the scripts, and MUST NOT be able to write them.

#### Scenario: No player write path exists
- **WHEN** the bot interface is enumerated for endpoints that accept script text
- **THEN** no endpoint accepts script source from a player
- **AND** every script-mutating operation is reachable only from the LLM path

#### Scenario: A player reads the script their bot ran
- **WHEN** a player opens the script view for a bot they own
- **THEN** the source returned is the revision that bot is currently executing
- **AND** the response is read-only

#### Scenario: A player cannot read another player's script
- **WHEN** a player requests the script view for a bot they do not own
- **THEN** the request is refused

### Requirement: Script Execution Is Sandboxed And Tick-Bounded
Each bot's script MUST run in its own sandbox with a memory limit and a CPU
limit per tick. The script MUST NOT have filesystem access and MUST NOT have
network access.

A script that exceeds its per-tick CPU limit MUST be stopped for that tick, and
the overrun MUST NOT propagate into the game server tick.

The runner MUST execute scripts outside the game server process, so that a
script that hangs cannot stall the server.

#### Scenario: A hanging script does not stall the server
- **WHEN** a bot's script does not return within its per-tick CPU limit
- **THEN** that script's tick is terminated
- **AND** the server tick proceeds on time

#### Scenario: Sandbox denies escape attempts
- **WHEN** a script attempts filesystem or network access
- **THEN** the attempt fails inside the sandbox
- **AND** no host resource is reached

#### Scenario: One bot's runaway script does not affect another bot
- **WHEN** one bot's script exhausts its memory limit
- **THEN** only that bot's sandbox is terminated
- **AND** other bots' scripts continue to run

### Requirement: Scripts Act Only Through The Existing Bot Actions
A script MUST act on the world only by invoking the bot actions the agent
already dispatches, and MUST NOT reach past that surface to the server or to
the mod's internals.

#### Scenario: Script action maps to a dispatched bot action
- **WHEN** a script invokes an action that exists in the agent's action dispatch
- **THEN** the action is executed with the same behaviour as when the LLM
  requests it directly

#### Scenario: Unknown action is refused
- **WHEN** a script invokes an action name that is not in the dispatch set
- **THEN** the call fails and reports the unknown action
- **AND** nothing is executed on the server

### Requirement: Per-Tick Snapshot Is Read-Only
Each tick the script MUST receive a read-only snapshot of the bot's state,
including health, food, position, inventory, nearby blocks and mobs, task
progress and recent events.

Mutations to the snapshot by the script MUST NOT affect the bot's real state.

#### Scenario: Script sees current state each tick
- **WHEN** a tick begins
- **THEN** the snapshot reflects the bot's state at that moment

#### Scenario: Snapshot mutation does not change world state
- **WHEN** a script writes to a field of its snapshot
- **THEN** the bot's actual inventory and position are unchanged

### Requirement: Code Time Is Metered Per Bot And Attributed To Its Owner
The runner MUST measure the script execution time each bot consumes, where the
time is spent, and MUST attribute it to the player who owns that bot.

Metering MUST run in the first release, even while the daily cap is unlimited,
so that a cap enabled later has a measured basis.

#### Scenario: Execution time is recorded against the owning player
- **WHEN** a bot runs a script for a measurable duration
- **THEN** that duration is recorded against the player who owns the bot

#### Scenario: Metering is present while the cap is unlimited
- **WHEN** the daily cap is set to unlimited
- **THEN** usage is still recorded

### Requirement: Daily Code-Hour Cap Is Per Player And Set In Mod Settings
The daily cap MUST be per player, not per bot: a player owning several bots MUST
have their bots' usage summed against one daily allowance.

The cap MUST be configured in the mod settings, following the existing
`serverDir/config/aiplayermod-*.json` convention, and MUST default to unlimited.

When a player's daily allowance is exhausted, their bots' scripts MUST pause and
the bots MUST fall back to keeping themselves safe.

#### Scenario: Cap defaults to unlimited
- **WHEN** no cap is configured
- **THEN** scripts run without being stopped by the cap
- **AND** usage is still metered

#### Scenario: Usage from multiple bots counts against one player cap
- **WHEN** a player owning two bots has both run scripts
- **THEN** both durations count against that player's single daily allowance
- **AND** one bot's usage reduces the allowance available to the other

#### Scenario: Exhausted allowance pauses the script safely
- **WHEN** a player's daily allowance is exhausted
- **THEN** that player's bots stop executing scripts
- **AND** each bot continues to keep itself safe
- **AND** the condition is reported in the bot interface

### Requirement: The Existing Planner Remains Available As A Fallback
When a bot has no script, or its script is paused, the bot MUST remain
operable by the existing planner rather than becoming idle or unsafe.

#### Scenario: Bot with no script falls back
- **WHEN** a bot has no runnable script
- **THEN** the existing planner can still drive the bot

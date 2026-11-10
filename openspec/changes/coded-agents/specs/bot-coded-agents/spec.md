## ADDED Requirements

### Requirement: Script Authoring Is LLM-Only
Only the LLM MAY create or modify a bot script. The system MUST NOT expose any
path by which a player or any other client supplies script source.

Players MUST be able to read the scripts, and MUST NOT be able to write them.

The dashboard currently exposes no authentication of any kind: all 47 routes are
undecorated handlers taking no auth dependency, and the process binds 0.0.0.0.
Whichever way the owner settles the owner-cap question, this requirement cannot
be satisfied on the dashboard as it stands — "only the LLM path" needs a caller
identity to distinguish the LLM from everyone else. Implementers MUST NOT treat
the absence of a player-facing script endpoint as sufficient.

#### Scenario: No player write path exists
- **WHEN** the bot interface is enumerated for endpoints that accept script text
- **THEN** no endpoint accepts script source from a player
- **AND** every script-mutating operation is reachable only from the LLM path
- **AND** the script-mutating path is distinguishable from any other caller by an
  identity check, not merely by not existing

#### Scenario: A player reads the script their bot ran
- **WHEN** a player opens the script view for a bot they own
- **THEN** the source returned is the revision that bot is currently executing
- **AND** the response does not allow the script to be modified (read-only in
  the sense of not-writable; it is NOT immutable between views, because the LLM
  may have rewritten the script since the previous view)

> **OPEN QUESTION — ownership (blocks this requirement and the cap).** There is
> no bot-to-player ownership relation anywhere in the codebase: no ownership
> column in the agent state, no owner field in `bot-identity` (which specifies
> identity properties only), and the dashboard has no authentication at all —
> every route is an unguarded `@app.get`/`@app.post` with no user identity.
> "The player who owns the bot" therefore names something that does not exist.
> This requirement is deferred until the owner decides:
> (a) bots are bound to a player's Minecraft UUID, (b) bots are bound to a
> dashboard user, which requires building authentication, or (c) bots are not
> player-owned and the script view and cap are per-bot.
> Decision needed from the owner; **not** available for the implementer to
> invent.

#### Scenario: A player cannot read another player's script
- **WHEN** a player requests the script view for a bot they do not own
- **THEN** the request is refused
- (Deferred with the ownership question above. If the owner chooses (c), this
  scenario is removed by a spec delta and the cap is specified per-bot.)

### Requirement: Authoring Rejects Code That Cannot Run
When the LLM proposes a script, the system MUST validate it before it is stored
or executed. A proposal that fails validation MUST be discarded, and the bot's
previously working script MUST remain in force.

Validation MUST reject, at minimum: syntax that does not parse, invocation of an
action name outside the dispatch set, and attempts to reach the filesystem or
network. Validation MUST NOT be the only defence — the sandbox remains
authoritative at execution time.

The system MUST NOT store a script that failed validation, and MUST NOT leave a
bot with no script as a result of a failed authoring attempt.

#### Scenario: A syntactically invalid proposal is refused
- **WHEN** the LLM proposes a script that does not parse
- **THEN** the proposal is discarded and the reason is reported
- **AND** the bot keeps executing its previous script

#### Scenario: A failed authoring attempt does not disarm a working bot
- **WHEN** a bot is executing a valid script and a new authoring attempt fails
  validation
- **THEN** the bot continues executing the previously stored script
- **AND** no tick is missed and no task is interrupted

#### Scenario: Validation is not the only defence
- **WHEN** a script passes validation and later attempts a denied operation at
  execution time
- **THEN** the sandbox denies it at execution, exactly as for an unvalidated
  attempt

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

### Requirement: Daily Code-Hour Cap Is Set In Mod Settings (unit pending owner decision)
The daily cap is a single per-player allowance in the decision this text encodes:
a player owning several bots MUST have their bots' usage summed against one
daily allowance. **The unit of summation is decision-dependent and not yet
settled** — see the note below. The cap's existence, its configuration surface
and its default do not depend on that decision.

The cap MUST be configured in the mod settings, following the existing
`serverDir/config/aiplayermod-*.json` convention, and MUST default to unlimited.

When a player's daily allowance is exhausted, their bots' scripts MUST pause and
the bots MUST fall back to keeping themselves safe.

> **The unit of the cap is deferred with the ownership question above.** The
> owner's decision was a *per-player daily* cap, and that is what this text
> encodes — but summing "a player's bots" requires the bot-to-player relation
> that does not exist. Metering and pause-on-exhaustion are specified now and are
> unaffected; only the summation unit waits on the decision. If the owner chooses
> (c), the unit becomes per-bot and the scenario below is rewritten as a spec
> delta, not silently dropped.

#### Scenario: Cap defaults to unlimited
- **WHEN** no cap is configured
- **THEN** scripts run without being stopped by the cap
- **AND** usage is still metered

#### Scenario: Usage from multiple bots counts against one player cap
- **WHEN** a player owning two bots has both run scripts
- **THEN** both durations count against that player's single daily allowance
- **AND** one bot's usage reduces the allowance available to the other
> (Deferred with the ownership question. Becomes a per-bot scenario if the owner
> chooses (c).)

#### Scenario: Exhausted allowance pauses the script safely
- **WHEN** a player's daily allowance is exhausted
- **THEN** that player's bots stop executing scripts
- **AND** each bot continues to keep itself safe
- **AND** the condition is reported in the bot interface

### Requirement: A Script Swap Takes Effect At A Tick Boundary
When the LLM replaces a bot's script, the new revision MUST take effect at a
tick boundary, never part-way through a tick. A bot MUST NOT execute one
revision's actions under another revision's state.

Each stored script MUST carry a revision identifier that changes when its
content changes, so that "the revision the bot is currently executing" is
answerable. The identifier MUST NOT change when the content does not.

#### Scenario: A swap does not split a tick
- **WHEN** a new revision is stored while a tick is in progress
- **THEN** the in-progress tick completes under the old revision
- **AND** the next tick begins under the new revision

#### Scenario: The executed revision is identifiable
- **WHEN** a player or operator asks which script a bot is running
- **THEN** the answer names a specific revision
- **AND** a stored script whose content did not change reports the same revision

### Requirement: An Unreachable Runner Is Detected And Falls Back
The runner is a new failure domain between the agent and every bot's behaviour.
The system MUST detect that the runner is unreachable or not answering, and MUST
NOT let a bot silently stop acting while its stored script still appears current.

While the runner is unreachable the affected bots MUST fall back to the existing
planner, and the condition MUST be reported in the bot interface rather than
inferred by a player from a motionless bot.

Recovery MUST NOT require the bot to be restarted, and MUST NOT replay actions
the bot already took before the interruption.

#### Scenario: A bot does not stall silently when the runner is gone
- **WHEN** the runner becomes unreachable while bots have scripts stored
- **THEN** each affected bot falls back to the existing planner
- **AND** the condition is reported in the bot interface
- **AND** no bot continues to report a script as executing while running none

#### Scenario: Recovery does not duplicate work
- **WHEN** the runner becomes reachable again
- **THEN** each bot resumes under its stored script without being restarted
- **AND** actions completed before the interruption are not replayed

#### Scenario: An unresponsive runner is not mistaken for a slow tick
- **WHEN** the runner accepts a connection but does not answer within the bound
  the agent allows
- **THEN** the runner is treated as unreachable for that bot
- **AND** the per-tick bound still holds for the game server

### Requirement: The Existing Planner Remains Available As A Fallback
When a bot has no script, or its script is paused, the bot MUST remain
operable by the existing planner rather than becoming idle or unsafe.

#### Scenario: Bot with no script falls back
- **WHEN** a bot has no runnable script
- **THEN** the existing planner can still drive the bot

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

### Requirement: Runner Contract v1 Is Frozen Before The Runner Is Built
The runner is one shared service consumed by more than one game. Its interface
MUST be frozen as **contract v1** before the runner or the sandbox is built,
because a change to a contract another team has pinned is a rebuild for them,
not a version bump.

Contract v1 MUST specify, at minimum: tick delivery and cadence; transport;
runner↔server authentication; the snapshot schema; the `api.*` call shapes
including what a call returns when it is rejected; `script.get`, `script.put`
and `script.logs`; the active/degraded/disabled fallback states; and the limits
table below. Every limit MUST be a contract field with a value and a unit, not
an adverb.

The contract is not frozen until it has been reviewed by the minecraft reviewer
**and** sent to `cardgame-lead` as a queue row. Both are acceptance conditions.

#### Contract v1 — limits

Numeric initial values come from the cardgame proposal's Limits table
(`~/evidence/2026-11-10-js-agent-scripts/cardgame-PROPOSAL.md:110-124`), so both
games start from the same runner numbers. Which limits exist comes from this
capability's own proposal
(`~/evidence/2026-11-10-js-agent-scripts/PROPOSAL.md:26-44`), which names a heap
limit, a stack limit, a CPU budget per tick and per-bot rate limits. Each is a
field; none may be enforced as a default the contract does not name.

**One of the four did not survive measurement.** The proposal assumed a stack
limit was a settable control. It is not: on the pinned build the overflow depth
is fixed at 2362 frames, `setMaxStackSize()` does not move it, and the overflow
is not catchable in-script — it kills the host process. The limit rows below
record what was measured, and stack exhaustion is contained by process
isolation instead. See "Measured: stack depth and its failure mode".

| Limit | Value | Unit | Enforced by |
|---|---|---|---|
| Heap per sandbox | 32 | MB | runner memory limit |
| CPU per tick | 20 | ms | runner interrupt handler; per-tick CPU reported to the game, which applies its own cap |
| Wall clock per host call | 2 | s | runner |
| Host calls per tick | 8 | count | runner |
| Tick rate per bot | ≤ 1 | per second | runner owns the loop; the mod schedules directive work |
| `api.log` | 1 KB/line, 100 lines/min | size, rate | server |
| Script source | 64 KB, 20 versions | size, count | server |
| Script memory (`api.remember`) | 16 | KB per bot | server |
| Consecutive errors before fallback | 3 | count | server; the LLM is woken on the first |
| Daily code hours per player | unlimited | hours/day | server metering (owner decision B) |
| **Stack depth per script call** | **2362 frames (measured)** — but see the note: the limit is **not settable** and overflow is **not catchable** | frames | runner: must be contained by process isolation, not by a stack setting |
| **`api.do` rate** | 30 | calls/min per bot | runner (see the rate reasoning below) |
| **`api.say` rate** | 30 | calls/min per bot | runner |
| **`api.send` rate** | 20 | calls/min per bot | runner |
| **`api.log` retention** | **unstated for v1** | — | not specified; an implementer MUST NOT adopt cardgame's 7-day term by default |

#### Measured limits and their sources (probe, 2026-11-10)

Measured on `quickjs-emscripten@0.32.0`, release-asyncify variant, Node
22.23.3, throwaway probe under `agent-script-runner/probe/` (forked child per
run so the failure was observed rather than fatal to the probe).

- A script that recurses without a base case reaches **depth 2362** and dies
  with `RangeError: Maximum call stack size exceeded`.
- **The failure is not catchable inside the script.** A `try { rec(0) }
  catch (e) {}` around the recursion does not contain it; the error surfaces as
  a host-level `uncaughtException` and **the Node process exits**. A script can
  therefore kill the runner process, not just its own tick.
- **`runtime.setMaxStackSize()` does not change the depth.** Values from
  256 KB to 4 MB all failed at exactly 2362 frames — the call exists and
  accepts the argument but the asyncify build's stack is fixed. Picking a
  "safe" number here is not available, because there is no number to pick.

**Consequence for the design, and it is a design change not a table value:**
stack exhaustion MUST be contained by **process isolation** (the runner runs
each bot's script in a child/worker process it can lose), not by a stack-depth
setting or an in-script try/catch. The per-tick CPU limit alone does not cover
this: a recursion overflow is not a slow tick, it is a dead process. This
constrains 4.1's service shape and is recorded as task 2.6.

**How the three rates were chosen.** These are policy, not measurements, and
each is anchored to the existing directive cadence rather than to a round number.
`TICK_DELAY` is 2.0 s (`agent/config.py:89`), so an LLM-driven bot issues at most
**30 actions per minute** — one per tick. A script must not be able to exceed the
rate at which the bot it replaces already acts, or scripted bots would load the
shared 4-thread API pool harder than the LLM bots do:

- **`api.do` = 30/min per bot** — one per tick at the existing 2.0 s cadence,
  i.e. parity with the LLM path, not headroom above it.
- **`api.say` = 30/min per bot** — same bound; chat is capped by the same tick
  loop and there is no reason for it to outpace action.
- **`api.send` = 20/min per bot** — below the tick rate: messages between bots
  are coordination, not the bot's primary act, and `api.send` is the call most
  likely to be used in a burst.

These are revisable in shadow mode once real pool load is observed; the
reasoning above is what a reviser must beat, not just the number.

The three rate rows are this binding's own. `api.log` is a shared name whose
limit was carried across from cardgame's table because both games cap it the
same way, except that **retention is unstated here** — cardgame's table carries a
7-day term that this one does not. cardgame's `api.ask` limit belongs to its
namespace and was not carried across.

**No row is TBD as of the 2026-11-10 probe.** The stack row was resolved by
measurement into something stronger than a number — a design constraint that it
cannot be set or caught. The three rates are policy values with the reasoning
above. `api.log` retention is recorded as *unstated for v1*, which is a decision,
not a gap: it is not to be inherited from cardgame. 1b.2 now means "re-measure
and confirm", and reopens a row by adding a measurement, not by guessing.

#### Scenario: Contract v1 is frozen before the runner code exists
- **WHEN** implementation of the runner or the sandbox begins
- **THEN** contract v1 is frozen and carries both acceptance marks: reviewer
  PASS, and a `cardgame-lead` queue row recording that it was sent
- **AND** both games pin the same contract version

#### Scenario: A limit is a field, not an adverb
- **WHEN** the contract is read for any limit in the table
- **THEN** it names a value, a unit and where the limit is enforced
- **AND** a limit that is not yet measured is marked TBD with how it will be
  measured, rather than given a plausible number

### Requirement: The Script API Is The Minecraft Binding
Contract v1 fixes the **shared** runner and sandbox surface: tick delivery,
snapshot envelope, the limits table and the transport. It does not fix any
game's action vocabulary. Each game binds its own `api` namespace; for this
capability that namespace is Minecraft's, and it MUST NOT be cardgame's
(`api.battle.act`, `api.world.*`, `api.ask`) — those name a board, a world order
and a strategic question that this game does not have.

`api.log` is shared by name but not by meaning: both games log, so it appears in
both namespaces and is not evidence that either was copied from the other. Its
limit **was** carried across from cardgame's table because both games cap logging
the same way (see the limits table) — with one difference: **retention is
unstated in this binding for now.** Cardgame's table carries a 7-day retention
term and this one does not. An implementer MUST NOT adopt cardgame's retention
value by default; if retention is needed it is added to this table by a spec
delta, with its own measurement.

The Minecraft binding is:

| Call | Shape | Returns |
|---|---|---|
| `api.do(directive, args)` | directive name plus its arguments | accepted, or a rejection with a reason; the directive's **result arrives later as an event** |
| `api.say(text)` | text | accepted, or a rejection with a reason |
| `api.send(otherBot, msg)` | bot name plus message | accepted, or a rejection with a reason |
| `api.remember(key, value)` | key plus value | accepted, or a rejection with a reason |
| `api.log(text)` | text | accepted (log volume is capped by the limits table) |

`api.do` MUST reuse the directives that already run the bots rather than
re-implementing behaviour in JavaScript, so pathfinding, mining and crafting
stay in the tested Java code. The directive name MUST be one the agent
dispatches; a name outside that set is refused and executes nothing.

Every call MUST be rate-limited per bot, and the rate MUST be a contract field
(see the limits table).

#### Scenario: A directive is accepted and its result arrives as an event
- **WHEN** a script calls `api.do("mine", target)` and the call is accepted
- **THEN** the call returns promptly and does not block for the directive's
  completion, because a directive runs for many ticks
- **AND** the directive's result arrives in a later tick's event list

#### Scenario: A rejected call reports why
- **WHEN** a script calls an action with a directive name outside the dispatch
  set, or exceeds its rate
- **THEN** the call is rejected with a reason the script can read
- **AND** nothing is executed on the server

#### Scenario: The minecraft binding is not the cardgame one
- **WHEN** a script calls `api.battle.act` or `api.ask`
- **THEN** the call fails as an unknown host function
- **AND** the failure is reported in the same way as any other unknown call

### Requirement: Host Calls Are Asynchronous
Host calls from a script to the game MUST be asynchronous: the script awaits
them, and the runner does not block its event loop while a game server answers.
This is why the asyncify build of the engine is pinned.

An awaited host call MUST count against both the per-call wall-clock limit and
the per-tick budget of the script that issued it. A script that awaits must not
escape metering by doing so.

#### Scenario: A script awaits a host call
- **WHEN** a script calls a host function and awaits it
- **THEN** the call is asynchronous and the runner serves other bots while it is
  outstanding
- **AND** the time the call takes counts toward its per-call wall clock and its
  per-tick budget

#### Scenario: Awaiting does not escape the tick budget
- **WHEN** a script issues host calls that together exceed its per-tick budget
- **THEN** the budget is exhausted exactly as for CPU the script spends itself
- **AND** the script is stopped for that tick

### Requirement: Script Execution Is Sandboxed And Tick-Bounded
Each bot's script MUST run in its own sandbox with a memory limit and a CPU
limit per tick. The script MUST NOT have filesystem access and MUST NOT have
network access.

A script that exceeds its per-tick CPU limit MUST be stopped for that tick, and
the overrun MUST NOT propagate into the game server tick.

The runner MUST execute scripts outside the game server process, so that a
script that hangs cannot stall the server.

Isolation MUST also survive a script that **kills its execution context**, not
only one that hangs or overruns. Measurement on the pinned engine (see "Measured:
stack depth and its failure mode") shows unbounded recursion raises a host-level
error that an in-script `try/catch` cannot catch, at a fixed depth, and that the
engine's stack-size setting does not change it. The runner MUST therefore run
each bot's script in a process or worker it can lose and replace, MUST NOT
depend on a stack-depth setting or an in-script catch to contain this, and MUST
count a dead worker as an error toward the consecutive-error fallback rather
than as a healthy bot.

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

#### Scenario: A script that kills its execution context is contained
- **WHEN** a bot's script recurses until the engine raises a stack error
- **THEN** only that bot's worker dies and is replaced
- **AND** the death is counted toward the consecutive-error fallback for that bot
- **AND** other bots' scripts keep running and the runner process survives

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
- **AND** the revision the bot resumes under is the one identified by the
  revision-identity rule below ("A Script Swap Takes Effect At A Tick
  Boundary"), so an interruption cannot make a bot resume under a revision
  other than the one it reports

#### Scenario: Repeated flapping does not leave a bot waiting
- **WHEN** the runner becomes unreachable and reachable three consecutive times
  while the agent has a bot waiting on it
- **THEN** each timeout releases the waiting agent
- **AND** no bot is left waiting on a request that will never answer
- **AND** the third flap leaves the bot in a defined state, not an accumulating
  one

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

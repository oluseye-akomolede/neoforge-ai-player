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
and `script.logs`; the per-tick outcome classes (the runner reports these rather
than owning bot states); and the limits table below. Every limit MUST be a
contract field with a value and a unit, not an adverb.

The contract itself is written in `contract-v1.md` beside this change. Stating
the requirements without the document was a defect: this section says what the
contract must contain, and a list of requirements is not a contract.

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

**The stack limit IS a settable control — and one earlier measurement of mine
was wrong about that.** A first probe reported that `setMaxStackSize()` had no
effect. It had none *in that probe*: it set the limit on a runtime and then
evaluated in a context created by a different call, which carries its own
runtime, so the limit never applied. Corrected and re-measured (see "Measured:
stack depth and its failure mode"), the limit works, and it works **only below
a host ceiling**. Both regimes matter and the limit rows below record both.

| Limit | Value | Unit | Enforced by |
|---|---|---|---|
| Heap per sandbox | 32 | MB | runner memory limit |
| CPU per tick | 20 | ms | runner interrupt handler; per-tick CPU reported to the game, which applies its own cap |
| Wall clock per host call | 2 | s | runner |
| Host calls per tick | 8 | count | runner |
| Tick rate per bot | ≤ 1 per second (a ceiling; every active script is also ticked at this cadence, never less) | rate | the game drives the tick and sends it; "runner owns the loop" means the sandbox-execution loop, not tick initiation |
| `api.log` | 1 KB/line, 100 lines/min | size, rate | server |
| Script source | 64 KB, 20 versions | size, count | server |
| Script memory (`api.remember`) | 16 | KB per bot | server |
| Consecutive errors before fallback | 3 | count | server; the LLM is woken on the first |
| Daily code hours per bot | unlimited | hours/day of **wall-clock active script time**, not CPU | game-side metering (owner decision B; unit per bot, 2026-11-10 14:12Z) |
| **Stack size per runtime** | **256 KB** (measured: 1362 frames, overflow **catchable**, runtime survives) | bytes | runner: `setMaxStackSize` on the runtime that also creates the context |
| **`api.do` rate** | 30 | calls/min per bot | runner (see the rate reasoning below) |
| **`api.say` rate** | 30 | calls/min per bot | runner |
| **`api.send` rate** | 20 | calls/min per bot | runner |
| **`api.log` retention** | **unstated for v1** | — | not specified; an implementer MUST NOT adopt cardgame's 7-day term by default |

#### Measured limits and their sources (probe, 2026-11-10)

Measured on `quickjs-emscripten@0.32.0`, release-asyncify variant, Node
22.23.3, throwaway probe under `agent-script-runner/probe/` (forked child per
run so the failure was observed rather than fatal to the probe).

There are **two regimes**, and the first probe only ever saw the second, which
is why its conclusion was wrong.

**Below the host ceiling the limit works.** With `setMaxStackSize` applied to
the runtime that also created the evaluating context (see `probe-stack-lead.mjs`,
and our re-check `verify-rt.mjs` / `verify-curve.mjs`):

| `setMaxStackSize` | depth reached | outcome |
|---|---|---|
| 64 KB | 338 | `InternalError` caught in-script, runtime usable afterwards (`1+1` = 2) |
| 256 KB | 1362 | `InternalError` caught in-script, runtime usable afterwards |
| 512 KB and above, or unset | ~2362 | **host stack overflows first**; Node dies, uncatchable |

So 256 KB is a real control with margin below the ~2362-frame host ceiling: a
runaway script raises an ordinary `InternalError` the script can catch, and the
runtime stays usable afterwards.

**Above the ceiling, no setting helps.** Past roughly 2362 frames the Wasm/Node
stack overflows before QuickJS can install its own guard. That is a dead
process, not a caught error, and no `setMaxStackSize` value prevents it — the
larger the limit, the more surely it happens.

**The bug the first probe had, now a required test.** It set the limit on a
runtime and then evaluated in a context created by a different call, which
carries its own runtime, so the limit never applied and every value behaved
identically. The only defence is to assert the relationship, so a test must
prove **every context is created from the limited runtime**
(`rt.newContext()`, not `mod.newContext()`).

**Consequence for the design — both parts, and they are not alternatives.**
The stack limit is the **first line**: it turns the common runaway script into a
catchable error inside the sandbox. Process isolation is **defence in depth** for
the regime the limit cannot govern — a host-level crash, a Wasm abort or OOM —
and is justified by *that*, not by the stack finding. Task 2.6 keeps process
isolation on that basis.

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

### Requirement: Host Calls Are Synchronous And Return Actions
A host call from a script MUST return inside the tick. It MUST NOT block waiting
for the game server to answer, and it MUST NOT cause the runner to call back into
the game. `api.do`, `api.say` and `api.send` MUST return an acceptance, and the
action they accept MUST be carried in the tick result for the game to execute.

A rejected call MUST return a rejection value the script can inspect and continue
from. A rejection is not an exception and MUST NOT end the tick.

Action outcomes MUST reach the script as events in a later tick's snapshot, not
as return values, because the action is executed by the game after the tick.

> **This requirement replaces "Host Calls Are Asynchronous".** The asynchronous
> design required the runner to call back into the game mid-tick, which needs a
> second transport, a second authentication leg in the opposite direction, an
> inbound endpoint on each game's server, and a callback timeout. Returning the
> actions in the tick result needs none of those, is one network direction, and
> works for cardgame, whose battle loop cannot tick on a runner clock. The
> asyncify build stays pinned (it is the build the stack limit was measured on),
> but it is no longer justified by host-call callbacks.

#### Scenario: A host call returns inside the tick
- **WHEN** a script calls `api.do` and reads the result on the next line
- **THEN** the call has already returned an acceptance or a rejection
- **AND** no round trip to the game server occurred during the tick

#### Scenario: A rejected call is a value, not a throw
- **WHEN** a script exceeds its host-call count and calls `api.do` again
- **THEN** the call returns a rejection the script can inspect
- **AND** the script continues executing that tick
- **AND** the tick is not recorded as a script error

#### Scenario: An accepted action is executed and its outcome arrives later
- **WHEN** a script's `api.do` is accepted in one tick
- **THEN** the game executes that action after the tick
- **AND** its outcome appears among the events of a later tick's snapshot

### Requirement: Script Execution Is Sandboxed And Tick-Bounded
Each bot's script MUST run in its own sandbox with a memory limit and a CPU
limit per tick. The script MUST NOT have filesystem access and MUST NOT have
network access.

A script that exceeds its per-tick CPU limit MUST be stopped for that tick, and
the overrun MUST NOT propagate into the game server tick.

The runner MUST execute scripts outside the game server process, so that a
script that hangs cannot stall the server.

Each runtime MUST set a stack size (256 KB, measured) and MUST create every
context from that same runtime, so that a runaway script raises a catchable
`InternalError` inside the sandbox rather than reaching the host stack. This is
the first line, and the test that proves it is specifically that the context
shares the limited runtime — the setting is silently inert otherwise.

Isolation MUST also survive a script that **kills its execution context**, not
only one that hangs or overruns. Past the host stack ceiling (~2362 frames on
the pinned build) the Wasm/Node stack overflows before QuickJS can act: a dead
process, uncatchable, and no `setMaxStackSize` value prevents it. The runner MUST
therefore also run each bot's script in a process or worker it can lose and
replace, and MUST count a dead worker as an error toward the consecutive-error
fallback rather than as a healthy bot. This containment is defence in depth for
host-level crashes (Wasm abort, OOM), which the stack limit cannot govern — not
a substitute for the limit.

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

#### Scenario: Unbounded recursion is a catchable error inside the sandbox
- **WHEN** a bot's script recurses without a base case at the configured 256 KB
  stack size
- **THEN** the script receives a catchable `InternalError`
- **AND** the runtime is still usable afterwards — a subsequent evaluation in
  the same context succeeds
- **AND** the runner process does not die

#### Scenario: Every context is created from the limited runtime
- **WHEN** the runner creates a context for a script
- **THEN** that context was created from the runtime carrying the stack size
- **AND** a context created from any other runtime is treated as a defect, not
  as a script error — the limit is silently inert in that case, and this is the
  exact bug the first probe had

#### Scenario: A script that kills its execution context is contained
- **WHEN** a bot's script exhausts the host stack despite the limit (Wasm abort,
  OOM, or any crash past the ~2362-frame ceiling)
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

### Requirement: Code Time Is Metered Per Bot

**A code hour is wall-clock time during which a bot's script is active** — not
CPU time. **The game MUST send no tick for a bot whose script is not active**,
so that every tick sent is an active-script tick. Given that, the game MUST count
each tick it sends by adding that tick's period to the bot's usage; it MUST NOT
count time from any other source, such as a wall clock reading between ticks.

A bot whose script is paused, disabled, deleted or fallen back to the planner
accrues nothing for the time it is not running one.

The converse direction is required too. **Given an active script, the game MUST
send a tick at the stated cadence** (the per-bot tick rate in the limits table is
a ceiling, not a floor; the real cadence is one tick per `TICK_DELAY` = 2.0 s,
so 0.5/s, which is the interval the `api.do`/`api.say` rates are derived from —
a floor equal to the 1/s ceiling would describe half the real interval). The
cap counts ticks, so an active script that is
simply not ticked accrues nothing and the hours-per-day allowance would silently
not apply — the same failure as counting CPU, reached from the other side.

The cap therefore measures, and can only measure, **active** time. Time a bot
spends disabled or fallen back to the planner is free: the fallback after three
consecutive non-`ok` ticks is itself a MUST, so a bot that fails often is
correctly ticked while active and correctly idle while disabled, and accrues
little. That is a property of the cap as specified, not a defect in it — an
operator turning the cap on should expect frequent fallbacks to read as low
usage rather than as an accounting error. Making the counter survive disabling
would be worse: it would bill a bot for time it was not allowed to run.

The runner MUST also report each tick's CPU time and where it was spent. That is
a **reported field for visibility and abuse checks, not the cap's unit**: a
few milliseconds of CPU per tick would take many days of wall-clock time to
reach an hours-per-day cap, so a cap counted in CPU would silently never fire.

No player identity is involved: the bot is the unit of both measurement and
summation.

Metering MUST run in the first release, even while the daily cap is unlimited,
so that a cap enabled later has a measured basis.

#### Scenario: Wall-clock time, not CPU time, accumulates
- **WHEN** a bot's script is active for one hour of game time, using only a few
  milliseconds of CPU per tick
- **THEN** that bot accrues one code hour
- **AND** the CPU time is recorded separately as a reported field

#### Scenario: An inactive script accrues nothing
- **WHEN** a bot's script is paused, disabled, deleted, or fallen back to the
  planner
- **THEN** no tick is sent for that bot
- **AND** its code hours stop increasing for that period
- **AND** its previously recorded usage is unchanged

#### Scenario: An active script is ticked, so its hours accrue
- **WHEN** a bot's script is active
- **THEN** the game sends it a tick at the stated cadence
- **AND** its usage keeps increasing at the wall-clock rate, rather than
  standing still for want of ticks

#### Scenario: Execution time is recorded per bot
- **WHEN** a bot runs a script for a measurable duration
- **THEN** that duration is recorded against that bot
- **AND** no player identity is required to record it

#### Scenario: Metering is present while the cap is unlimited
- **WHEN** the daily cap is set to unlimited
- **THEN** usage is still recorded

### Requirement: Daily Code-Hour Cap Is Set In Mod Settings
The daily cap is a **per-bot** allowance, configured in the mod settings
following the existing `serverDir/config/aiplayermod-*.json` convention, and
MUST default to unlimited.

The cap MUST be counted per bot. No player identity is required to enforce it,
and a bot's usage MUST NOT be summed with any other bot's: exhausting one bot's
allowance MUST leave every other bot's allowance intact, including another bot
owned by the same player.

When a bot's daily allowance is exhausted, that bot's script MUST pause and the
bot MUST fall back to keeping itself safe.

Per-player accounting is deliberately out of scope: it needs a bot-to-player
relation that does not exist. Adding it later is a separate change that requires
that identity first; it MUST NOT be introduced by reinterpreting this cap.

#### Scenario: Cap defaults to unlimited
- **WHEN** no cap is configured
- **THEN** scripts run without being stopped by the cap
- **AND** usage is still metered

#### Scenario: Each bot has its own allowance
- **WHEN** two bots, owned by the same player, have both run scripts
- **THEN** each bot's duration counts against that bot's own allowance
- **AND** one bot's usage does not reduce the allowance available to the other

#### Scenario: Exhausted allowance pauses the script safely
- **WHEN** a bot's daily allowance is exhausted
- **THEN** that bot stops executing scripts
- **AND** that bot continues to keep itself safe
- **AND** the condition is reported in the bot interface

#### Scenario: One exhausted bot does not stop another
- **WHEN** one bot's allowance is exhausted and another bot still has allowance
- **THEN** the other bot's script keeps running

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

#### Scenario: An instance loss is one event, not one failure per bot
- **WHEN** the runner instance is lost while many bots across both games have
  scripts stored
- **THEN** every affected bot falls back to the existing planner
- **AND** the condition is reported as a single runner-level condition, not as
  an independent per-bot fault raised simultaneously by every affected bot
- **AND** the number of dead-endpoint requests issued during the interruption
  does not grow with the number of affected bots: the runner is probed at a
  bounded rate, the same bound regardless of whether 2 bots or 264 are affected
- **AND** the operator can distinguish this instance-wide event from a fault
  confined to one bot, because the two arrive as different reported conditions:
  a **runner-level** condition naming the instance, and a **bot-level** fault
  naming the individual bot

> **Why this scenario exists.** Every other scenario in this requirement is
> about one bot or one waiting agent, and an instance loss is the one failure
> that hits all of them at once — up to 8 + 256 sandboxes across both games,
> every scripted bot falling back simultaneously. "The condition MUST be
> reported in the bot interface" then means 264 simultaneous reports, and a
> per-bot retry loop means the request count scales with the fleet against an
> endpoint known to be dead. Neither is the failure the single-bot scenarios
> describe. The bound above is stated as *does not grow with fleet size* rather
> than "at most N per tick" deliberately: the latter sets the ceiling at N while
> the prohibition is N, which are the same number and satisfy neither.

### Requirement: The Existing Planner Remains Available As A Fallback
When a bot has no script, or its script is paused, the bot MUST remain
operable by the existing planner rather than becoming idle or unsafe.

The runner MUST NOT own this state machine. It MUST report a per-tick outcome
from a fixed class list — `ok`; `script_error`; `cpu_exceeded`; `memory_exceeded`;
`stack_overflow`; `host_call_timeout`; `host_calls_exceeded`; `worker_died`;
`bad_action_shape`; `source_too_large` — and the game MUST map that outcome to
its own states. A bot MUST be disabled, and fall back to the planner, after three
consecutive non-`ok` ticks.

#### Scenario: Bot with no script falls back
- **WHEN** a bot has no runnable script
- **THEN** the existing planner can still drive the bot

#### Scenario: A failing script is disabled by its outcome classes
- **WHEN** a bot's ticks return non-`ok` outcomes three times consecutively
- **THEN** the game disables scripting for that bot and the planner drives it
- **AND** the runner was not asked to track the count between calls

#### Scenario: A single bad tick does not disable the bot
- **WHEN** a bot returns one non-`ok` outcome followed by `ok`
- **THEN** scripting continues and the bot is not disabled

### Requirement: A Reported Condition Has A Defined Shape
Several requirements here oblige the system to report a condition in the bot
interface — an exhausted allowance, an unreachable runner, a lost instance —
without this text saying what a reported condition *is*. An obligation with no
stated shape is satisfied by whatever the implementer emits, and the cheapest
wrong implementation is one identical entry per bot.

A reported condition MUST carry, at minimum: an identifier for the scope it
applies to (the bot, or the runner instance), a scope discriminator
distinguishing a bot-level condition from a runner-level one, a condition kind
drawn from a fixed vocabulary rather than free text, and the time it was first
observed.

Conditions MUST be deduplicated by scope and kind while they persist: a
condition that remains true MUST NOT be re-reported as a new entry on each
observation. Two bots and one instance in the same state MUST NOT produce a
number of stored conditions that grows with the number of ticks, or with the
number of bots for a condition that is not bot-scoped.

The vocabulary is fixed and closed for v1. These three kinds are the conditions
the requirements above oblige the system to report; a new kind requires a spec
delta, not an addition to this table in passing.

| Condition kind | Scope | Raised when |
|---|---|---|
| `allowance_exhausted` | bot | the allowance covering this bot is exhausted, so its script stops (the cap is per bot — see "Daily Code-Hour Cap Is Set In Mod Settings") |
| `script_disabled` | bot | a bot's ticks return non-`ok` outcomes three times consecutively, and the game disables scripting for it (see "The Existing Planner Remains Available As A Fallback") |
| `runner_unreachable` | runner | the runner instance is unreachable or not answering, deliberately not reported as one per-bot fault (see "An Unreachable Runner Is Detected And Falls Back") |

`script_disabled` is bot-scoped because the disabling is per bot on that bot's
own outcome history; `runner_unreachable` is runner-scoped for the reason the
instance-loss scenario gives. The two are distinguishable by scope even when a
bot is affected by both, which is the case the instance-loss scenario asks an
operator to read correctly.

#### Scenario: A persistent condition is one entry, not one per tick
- **WHEN** a condition remains true for a bot across many ticks
- **THEN** it appears once while it persists
- **AND** it is cleared or marked resolved when it ceases to be true

#### Scenario: A runner-level condition is not one entry per affected bot
- **WHEN** the instance is lost while 264 bots across both games have scripts
- **THEN** the interface carries one runner-level condition, not 264 bot-level
  entries
- **AND** each affected bot's fallback is visible through its own state rather
  than through a duplicated condition

#### Scenario: A bot-level condition names its bot
- **WHEN** a single bot's script is disabled by its outcome classes
- **THEN** the condition is scoped to that bot and identifies it
- **AND** it is distinguishable from a runner-level condition of the same kind

> **Relationship to the contract.** The contract fixes the per-tick outcome
> class list and the runner/game split; this requirement fixes what the
> interface *stores and shows*. The two are different, closed lists with
> different members and different lifetimes: an outcome is computed per tick and
> is transient, a condition is derived from outcomes and persists until cleared.
> `ok` is an outcome and never a reported condition. A condition kind named here
> MUST NOT be added to the contract's outcome classes, and an outcome class MUST
> NOT be reported as a condition without appearing in the table above.

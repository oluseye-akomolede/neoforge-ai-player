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

### Requirement: A Script Acts By Calling The API, Never By Returning
A script MUST emit an action by calling `api.do(kind, args)` during its tick.
The runner MUST collect a tick's actions solely from those calls and MUST
ignore the script's return value.

A script that returns an action instead of calling `api.do` MUST be treated as
proposing nothing. Silence in the agent log is not evidence that a script did
nothing: a script that runs, succeeds and calls nothing is indistinguishable
there from one whose action was discarded, so the actions a tick actually
collected are the only admissible evidence.

This is a contract, not an implementation detail. `agent/scripts/scout.js` was
written to `return [{kind: "STORE_ALL"}]` and end with a bare `tick();`. The
runner wraps the source as a function body and discards the value, so the
action never reached the mod: measured on TEST 2026-11-13, the committed script
returned `{"status":"ok","actions":[]}` on every tick while a probe identical
except for calling `api.do` returned
`actions:[{"directive":"STORE_ALL"}]`. The test that should have caught it
rewrote the script's `tick();` into `;return tick();` before evaluating it and
stubbed `api.do`, so it asserted on a contract the runner does not implement.

#### Scenario: An action emitted through api.do reaches the bot
- **WHEN** a script calls `api.do` with a directive the dispatch set knows
- **THEN** the tick's collected actions contain that directive, in call order
- **AND** the agent dispatches it as it would an action the planner requested

#### Scenario: A returned action produces nothing
- **WHEN** a script returns an action object from its tick instead of calling
  `api.do`
- **THEN** the tick's collected actions are empty
- **AND** nothing is dispatched to the bot

#### Scenario: A silent tick is not read as a successful one
- **WHEN** a script completes a tick without calling `api.do`
- **THEN** the tick reports zero actions
- **AND** that zero is distinguishable from a discarded action by inspecting
  the collected actions, because the agent log carries no line either way

#### Scenario: The script under test is the script that is deployed
- **WHEN** the test suite exercises a script's action behaviour
- **THEN** it evaluates the committed source unmodified through the runner's
  real engine
- **AND** it asserts against the actions that engine collected, not against a
  return value and not through a stubbed `api.do`

### Requirement: A Runner Action Record Is Translated At The Agent Boundary
The runner's action record and the agent's binder input MUST NOT be assumed to
be the same shape. A tick's runner record carries `{seq, call, directive, args}`
and is the shared contract, consumed by other callers as well as the agent; the
agent MUST translate each record into its binder's input shape at the single
point where the runner's output enters the agent, rather than widening the
binder to read the runner's field names.

Translation MUST map a `do` record to `kind = directive` with `args` flattened
into the same object, treating `args` that are absent or null as no arguments.
It MUST refuse, visibly and with the record's `seq`, each of: a record whose
`call` is not `do`; a `directive` that is missing or not a non-empty string;
`args` that are not an object; and an `args` key named `kind` or `action`, which
the binder would read as the action name and so lose the real directive.

A refusal MUST NOT be silent and MUST NOT discard the other records in the same
tick. The `seq` MUST appear on both the refusal and the dispatch log line, so
the agent log can be matched to the script's own call.

This is a contract, not an implementation detail. `bind_action` reads `kind`
(or `action`) and refuses every key outside its argument allow-list, so a
runner record was refused three ways at once (`seq`, `call`, `args`) and the
`directive` never read. Measured on TEST 2026-11-13: after the script was fixed
to call `api.do`, every tick was refused with
`"action has no 'kind': {'seq': 1, 'call': 'do', 'directive': 'STORE_ALL', 'args': {}}"`.
`test_action_binding.py` fed only `{"kind": ...}` fixtures, so the binder's
tests agreed with the binder and nothing compared them to the producer.

#### Scenario: A runner record is bound as the directive it names
- **WHEN** a tick's runner record is `{seq, call: "do", directive, args}`
- **THEN** the agent binds it as `kind = directive` with `args` flattened in
- **AND** the bound action's dispatch log line carries the record's `seq`

#### Scenario: A malformed runner record is refused visibly
- **WHEN** a runner record has a `call` other than `do`, no usable `directive`,
  non-object `args`, or an `args` key named `kind` or `action`
- **THEN** that record is refused with a reason naming the fault and its `seq`
- **AND** the other records in the same tick are still bound and dispatched

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
accrues nothing for the time it is not running one. A bot whose script is **held
for a player goal** accrues nothing for the duration of the hold either: holding
is one of the ways a script is not active, so no tick is sent and no time is
counted. That follows the same rule as the other four and is stated here because
the hold is new.

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
  bounded rate, the same bound regardless of whether 2 bots or 72 are affected
- **AND** the operator can distinguish this instance-wide event from a fault
  confined to one bot, because the two arrive as different reported conditions:
  a **runner-level** condition naming the instance, and a **bot-level** fault
  naming the individual bot

> **Why this scenario exists.** Every other scenario in this requirement is
> about one bot or one waiting agent, and an instance loss is the one failure
> that hits all of them at once — up to 8 + 64 sandboxes across both games,
> every scripted bot falling back simultaneously. "The condition MUST be
> reported in the bot interface" then means 72 simultaneous reports, and a
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

### Requirement: A Player Goal Yields A Running Script

Earlier requirements make the planner and the script alternatives: the planner
is the fallback when no script runs. They do not say what happens when a player
addresses a bot that *is* running a script, and the omission is observable —
measured on 2026-11-19, a chat goal reached the planner while the script ticked,
and both issued store work for the same intent. (The two are not even sequential
alternatives at the call site: `_maybe_plan` runs before `_run_script_tick` every
iteration, so without this requirement both run each pass.)

**A player goal MUST take precedence over a running script.** While a bot's
script is active and a player instruction is accepted, the game MUST hold the
script — dispatching no script actions — and MUST run the instruction through
the planner. When the instruction's directive reaches a terminal state, the game
MUST resume the script.

Which chat counts as an instruction is the set the planner already admits, and
that set is fixed here to four gates rather than referred to as a moving target:

| Gate | Where | Effect |
|---|---|---|
| not the bot itself | `AIPlayerMod.java:272` | the bot's own chat is not an instruction |
| not purely a pleasantry | `agent.py:530` (`chat_filter.is_pure_pleasantry`, `chat_filter.py:27-42`) | "k", "ok", "hi <name>" alone are dropped; "Hi <name>! Who are you?" is not |
| not bot-origin | `agent.py:534` (`sender in _all_runners`) | a message from another bot is not a player instruction |
| not while following | `agent.py:539`, `agent.py:598`, `agent.py:642` | a bot already following a player does not take a new planner instruction |

This requirement MUST NOT widen or narrow that set: a message that would not
reach the planner MUST NOT yield a script either. **Any change to those four
gates MUST either leave this set unchanged or modify this requirement in the
same change** — the gates are named so that changing one without visiting this
requirement is a visible omission, not a silent behaviour change.

**A stale or non-goal cancel MUST NOT resume the script.** Chat can interrupt an
in-flight directive without satisfying any of the four gates: the poll path
reports `interrupted_by_chat` and the caller cancels on a new player message
without re-applying the pleasantry filter. A script held for a goal MUST resume
only when that goal's own directive reaches a terminal state. A cancellation
caused by chat that did not itself yield a goal MUST leave the script held, not
resume it.

**A held tick MUST be expressible as its own outcome.** The script-tick call
returns a bare boolean today (`agent.py:2719`; every path is `True` or `False`),
and `False` already means "the planner should run this tick" — the fallback the
memory clause above forbids. A hold is a third outcome: neither "the script
handled this tick" (`True`) nor "the script did not run, so the planner may"
(`False`). If the hold cannot be expressed distinctly, the first implementation
will encode it as `False` and the fallback returns one layer down. While a tick
is held the script MUST NOT resume and the planner MUST NOT dispatch on account
of it. The same string must not mean opposite things: `interrupted_by_chat` is
today both the reason a directive is cancelled (`agent.py:2258`) and, to the
script's own dispatch loop, a reason to report the tick handled
(`agent.py:2971`); a cancel that leaves the script held MUST be distinguishable
from that.

**A held goal MUST NOT cancel the planner run it is holding for.** The planner
starts before the script tick: `_maybe_plan` runs first in the iteration
(`agent.py:3098`) and, on accepting a chat goal, spawns the orchestrator daemon
thread for *that goal* (`agent.py:678`); `_run_script_tick` runs second
(`agent.py:3106`). The hold's job is therefore to suppress the *script's*
dispatch, not to stop the planner — the planner run that already started is the
player's own goal, and it MUST be allowed to proceed. Calling
`_cancel_orchestrator` from the hold is a DEFECT: at hold time no `_orch_cancel`
is published yet, so it latches `_orch_stop_pending` (`agent.py:1281`), and the
very planner this goal spawned honours that latch at its start
(`agent.py:1558-1561`), finalising the goal "cancelled" within a tick. Measured
on TEST (lead, 11-19 17:38Z): held at 17:27:53.5828, "stop pending" the same
millisecond, "honoring pending stop at orchestrator start" at 17:27:53.6216,
"plan cancelled between subtasks" at 17:27:54.2178 — the player's goal never
ran. The hold MUST reach only the script; it MUST NOT set `_orch_stop_pending`
and MUST NOT set any live run's cancel event.

**One goal owns the hold.** `_maybe_plan` is called for every message in the
batch, and each accepted chat goal spawns its own orchestrator thread; a hold
records the goal that most recently began one as its owner, replacing any
earlier owner. A hold MUST resume only on the terminal state of the directive
it is holding, and a stale terminal state from an earlier goal MUST NOT resume
a script a newer goal now holds. (Note: the nav-shortcut path at `agent.py:520`
does cancel the live orchestrator, but that is the shortcut's own stop and is
independent of a hold — a hold itself must not cancel, per the requirement
above.)

**The hold MUST carry cause and identity, not a bare flag.** `_orch_stop_pending`
is a single latched boolean with real callers (`agent.py:340` reset, `:520` nav
shortcut) and no record of who set it: it is set unguarded at `:1281` and cleared
by whichever thread consumes it at `:1558-1561`. That is adequate for stop and
reset, which are terminal. A hold is recoverable and fires far more often, so
reusing this latch for a hold would cause the holding goal's own orchestrator to
consume the latch and cancel itself. A hold MUST therefore be its own state, not
this latch, and the resume MUST consult the holding goal's own outcome rather than
a bare flag. The state MUST
identify the goal that owns the hold, so that "held by goal A" and "held by goal
B" are distinguishable; identity is already the idiom for this at `agent.py:1584`
(`if self._orch_cancel is cancel_event`), and a cancel that leaves the script
held MUST be distinguishable both from a player "stop" and from a supersede by a
later goal. The pre-existing unguarded set/clear at `:1281` and `:1559` is not
this requirement's to fix, but the hold MUST NOT widen it: a hold that is made
routine must not rely on an unlocked latch.

**Memory MUST survive the hold.** While held, the game MUST NOT advance, clear
or re-encode the remembered value, and MUST NOT construct a new `ScriptTick`:
the object that resumes MUST be the object that was held. A hold is not a tick
and MUST NOT be delivered as one to the runner.

Holding MUST NOT be metered. Time a script is held for a player goal is time it
is not active, so it accrues nothing under code-time metering — the same reading
as paused, disabled, deleted or fallen back to the planner.

#### Scenario: A player goal holds the script and the planner acts
- **WHEN** a bot is running an active script against a reachable runner and a player sends it an instruction
- **THEN** the planner handles the instruction
- **AND** no script action is dispatched while the instruction's directive runs
- **AND** in a control run with the same script, no goal, and the same reachable
  runner, a script action IS dispatched — so "no action" is attributable to the
  hold and not to the script being inert

#### Scenario: A goal arriving in the same iteration runs and the script does not double-issue
- **GIVEN** a bot with an active script and a reachable runner
- **WHEN** a player goal arrives in the same loop iteration as a script tick
- **THEN** the planner run started for that goal proceeds — it is NOT cancelled
  by the hold (it is the goal the hold is waiting on)
- **AND** no script action is dispatched for that tick
- **AND** in a control run with the same script and runner but no goal, a script
  action IS dispatched — so "no script action" is attributable to the hold and
  not to a script that was inert

#### Scenario: A held script is not ticked
- **WHEN** a bot with an active script and a reachable runner is held for a player goal
- **THEN** the runner receives no tick for that bot during the hold
- **AND** in a control run with the same script and runner but no goal, the runner DOES receive a tick

#### Scenario: The script resumes with its remembered value after a completed goal
- **WHEN** a script whose remembered value is non-null is held for a player goal
  that reaches `COMPLETED`
- **THEN** the script resumes ticking
- **AND** the tick after the resume carries exactly the value that was remembered
  before the hold, and the resuming `ScriptTick` is the same object that was held

#### Scenario: The script resumes with its remembered value after a failed goal
- **WHEN** a script whose remembered value is non-null is held for a player goal
  that reaches `FAILED`
- **THEN** the script resumes ticking
- **AND** the tick after the resume carries exactly the value that was remembered
  before the hold

#### Scenario: A cancelled goal does not resume the script
- **WHEN** a script is held for a player goal and that goal's directive is
  cancelled by chat that did not itself satisfy the four gates
- **THEN** the script remains held
- **AND** the tick outcome for that iteration is distinct from both `True`
  (the script handled it) and `False` (the planner may act)
- **AND** the planner dispatches no directive as a result of that tick

#### Scenario: Held time is not metered
- **WHEN** a script is held for a player goal for a duration
- **THEN** none of that duration is added to the bot's code-time usage

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
- **WHEN** the instance is lost while 72 bots across both games have scripts
- **THEN** the interface carries one runner-level condition, not 72 bot-level
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

### Requirement: A Scripted Bot Acts Only When There Is Something To Do

A script MUST NOT propose an action on a tick where the action would be
pointless. An idle bot that keeps proposing work does not stand still: its
proposals are carried out, so it walks to a container, finds nothing to store,
and repeats on the next tick indefinitely. Acting conditionally is therefore a
correctness requirement, not an optimisation.

For a store action specifically, a script MUST propose it only when the bot's
inventory holds at least one item, and after proposing it the script MUST hold
for a cooldown of at least one tick before proposing it again. The cooldown
exists so that a store which keeps failing to complete — no reachable container,
a container that fills mid-store — cannot be re-proposed on every tick.

The inventory a script reads is the one the snapshot envelope carries at
`state.inventory`: it is the LIST of carried items, each with at least `slot`,
`item` and `count`. A bot carrying nothing gets an empty list.

The game's endpoint body is NOT this shape. `HttpApiServer.java:469` sends
`Map.of("inventory", ...)`, so the wire carries a one-key wrapper; `build_state`
MUST unwrap it and MUST NOT hand the wrapper to a script (`a81d5d19`). The same
holds for `state.nearby.blocks` (`:505`) and `state.nearby.mobs` (`:504`).

`state.nearby.mobs` reading the `entities` endpoint is deliberate, not a typo.
Three names are live for one thing at three layers: the endpoint and its wrapper
key are `entities` (`HttpApiServer.java:504`), the snapshot key is `mobs`
(`snapshot.py:119` maps them), and the script-facing accessor is `look.entities`.
A reader that "corrects" `mobs` to `entities` to match the endpoint would leave
every script reading an undefined key.

A *failed* or unusable read still degrades to an empty list, so a script MUST
treat an empty list as "no items" rather than inferring presence.

#### Scenario: Empty inventory proposes nothing
- **WHEN** a bot's snapshot reports an empty inventory and the bot is provably idle
- **THEN** the script proposes no store action on that tick

#### Scenario: Carried items and an idle bot propose one store
- **WHEN** a bot's snapshot reports at least one carried item and the bot is provably idle
- **THEN** the script proposes exactly one store action on that tick

#### Scenario: A repeated store is held off by the cooldown
- **WHEN** a script proposed a store action on an earlier tick and the cooldown has not yet elapsed
- **THEN** the script proposes no further store action, even if the bot is idle and still carrying items

> **Why this requirement exists.** The M2 first script proposed a store on every
> tick it was idle: measured on test 2026-11-18, 77 proposals in about three
> minutes. Every existing guard passed correctly — the snapshot was present, the
> health was fine, the task was provably idle — and the guard set simply had no
> member that asks whether there is anything to do. The bot was not malfunctioning
> in any way the earlier requirements describe: it was doing exactly what it was
> told, at a frequency nobody chose.
>
> The cooldown is a separate guard from the inventory check and both are needed.
> The inventory check alone still loops whenever a store fails to complete with
> the items still carried, which is the normal case for a bot with no reachable
> container: the condition that stops the first proposal is unchanged on the
> next tick.
>
> **The shape of `state.inventory` is recorded here because it is a trap, and the
> trap was previously recorded backwards.** `BotPlayer.getInventory()` is
> serialised through `HttpApiServer.java:469` as `Map.of("inventory", ...)`, so
> the ENDPOINT body is a wrapper object. An earlier revision of this note
> concluded from that `snapshot.state.inventory` is the wrapper too, and had the
> guard read `state.inventory.inventory`. That was a fix aimed at the wrong
> layer: the wrapper never should have reached `state` at all. `build_state` now
> unwraps it (`a81d5d19`, `snapshot._obs`), and `state.inventory` is the list.
>
> The two wrong readings fail DIFFERENTLY, which is why the shape is pinned by a
> test rather than a comment. Reading `.length` on a wrapper object gives
> `undefined`: a silent false, and the guard proposes nothing forever. Unwrapping
> a list is not silent — `state.inventory.inventory` is `undefined`, and `.length`
> on that throws. The shipped guard survives it only because it tests
> `Array.isArray` first, so a throw never happens and a non-type falls closed to
> `[]`; a guard written as a bare `.length > 0` would raise instead. Quiet failure
> and a raise are different bugs with different fixes, so a test that only proves
> "proposes nothing" does not prove the guard is safe on the other shape. The
> contract is therefore: the producer sends a wrapper, `build_state` unwraps it,
> and the SCRIPT sees a list.
> A fixture that hard-codes either end alone will pass while the pair is broken
> — the wire shape and the script-visible shape must be asserted together.
> Fixtures MUST carry the real wrapper from `HttpApiServer.java:469/504-505` into
> `build_state`, and MUST also cover the degraded case, where an unusable read
> leaves `[]` plus a reader error.


### Requirement: A script's action gate MUST key on the directive status

A script that would start a job MUST open its gate when the producer reports NO
directive in flight, and MUST hold otherwise. "No directive in flight" SHALL be
established positively, from either of two producer fields:

- `directive.status` is a terminal status — `COMPLETED`, `FAILED` or `CANCELLED`
  (`DirectiveStatus.java`; serialised by `Directive.toMap()` as `status.name()`); or
- `progress.phase` is `"idle"` — a bot that has never been dispatched.

Any other shape MUST hold: an `ACTIVE` status, a status outside that set, a task
with no `directive`, or a task with no `progress` block. The absence of a field is
never evidence that the bot is idle.

The top-level `state` field MUST NOT be used as the discriminator. It carries the
active behaviour's `describeState()`, which for an idle bot is `"Standing by"`
(`IdleBehavior.java:24`), not the literal `"idle"`.

#### Scenario: A completed plan does not hold the bot
- **WHEN** the snapshot carries `state: "Standing by"`, a task whose
  `directive.status` is `"COMPLETED"`, and `progress.phase` of `"skill:done"`
- **THEN** the script proposes its action, because no directive is in flight

#### Scenario: Every terminal status is treated the same
- **WHEN** the task's `directive.status` is `COMPLETED`, `FAILED` or `CANCELLED`
- **THEN** the script proposes its action in all three cases, whatever stale
  `progress.phase` accompanies it

#### Scenario: An active directive still holds
- **WHEN** the task's `directive.status` is `"ACTIVE"`
- **THEN** the script proposes no action

#### Scenario: An unknown status is not read as finished
- **WHEN** the task's `directive.status` is a value outside the four defined ones
- **THEN** the script proposes no action

#### Scenario: A never-run bot acts
- **WHEN** the task carries no `directive` and `progress.phase` is `"idle"`
- **THEN** the script proposes its action

#### Scenario: The state field alone never opens the gate
- **WHEN** the snapshot's `state` is `"Standing by"` but the task carries an
  `ACTIVE` directive
- **THEN** the script proposes no action, so no test can pass by matching `state`

> **Why this requirement exists.** The gate introduced in M3-1 keyed on
> `progress.phase === "idle"` alone. That field is not a liveness signal: on every
> terminal path `BotBrain` sets `activeBehavior = idleBehavior` at `:96` (SUCCESS),
> `:109` (FAILED) and `:121` (CANCELLED) while `lastProgress` retains the
> behaviour's final phase, and `:187-190` keeps reporting it for as long as
> `lastDirective` is set — which is for the life of the process, since nothing
> clears it outside a reset. So after a bot's directory was first terminated, the
> gate held it permanently and it never acted again. Measured on test 2026-11-19:
> zero `[Scout/script]` dispatch lines for a bot holding 16 cobblestone.
>
> The question the gate is actually asking is "is a directive in flight", and
> `directive.status` answers it directly. The lead ruled the blocking UNINTENDED on
> 2026-11-19 and scoped the fix to the script, with no mod change: `currentPhase()`
> (`BotBrain.java:213-219`) reports the same retained phase and feeds the in-game
> overlay (`OverlayNetwork.java:1207`), where the last result after a directive ends
> is information a player is meant to see. Clearing `lastProgress` would remove
> shown information and require a mod build plus a server restart.
>
> **`state` looks like the answer and is not.** `BotBrain.java:180` writes
> `activeBehavior != null ? describeState() : "idle"`, which reads like an idle
> flag. But `activeBehavior` is assigned `idleBehavior` at construction (`:29`) and
> restored to it on every terminal path, so it is never null and the literal
> `"idle"` is unreachable in the PAYLOAD — an idle bot reports `"Standing by"`. The
> same nullable ternary at `stateLine()` (`:210`) does return `"idle"`, but only
> `OverlayNetwork.java:1208` and `OverlayScreen.java:1496` read that, and neither is
> the HTTP response a script sees. A gate written as `state === "idle"` would never
> fire: the same dead-guard class as the flat-shape health guard this script already
> carries a comment about, failing in the silent direction.


### Requirement: A held tick MUST be observable in the log

When a script declines to act because a directive is in flight, it SHALL emit
`api.log` on that tick naming what it held on — the directive status when there is
one, and the phase. A script that returns silently MUST NOT be the only evidence
that it ran.

#### Scenario: A busy bot produces a log line every tick
- **WHEN** the snapshot carries a task whose `directive.status` is `"ACTIVE"`
- **THEN** the script proposes no action and logs a line naming that status

#### Scenario: An unrecognised status is named as the reason
- **WHEN** the snapshot carries a task whose `directive.status` is not one of
  `ACTIVE`, `COMPLETED`, `FAILED`, `CANCELLED`
- **THEN** the script proposes no action and logs a line naming that status, so a
  reader can tell a status we do not recognise from a directive that is running

#### Scenario: A directive with no progress block is logged as unreadable
- **WHEN** the snapshot carries a task with no `progress` block at all
- **THEN** the script proposes no action and logs a line that says so, distinctly
  from a recognised non-idle phase

> **Why this requirement exists.** M3-1 added a task gate that holds unless the
> task is provably idle, which is the safe direction. It held silently. On test
> 2026-11-19, Scout was observed holding 16 cobblestone with no store for at least
> seven minutes, and the log carried ZERO script dispatch lines — so a bot being
> deliberately held, a bot the caller never invoked, and a script that was never
> reachable were indistinguishable from the outside. The investigation could not
> name a cause from the evidence because the code emitted no evidence.
>
> Naming the PHASE alone was not enough, which is why the line now leads with the
> status: since M3-1b the decision turns on `directive.status`, and a hold is
> almost always "a status we did not recognise" rather than a busy phase.

> **This requirement originally said it did not change the gate's decision. That
> is superseded by *A script's action gate MUST key on the directive status* below,
> which the lead ruled on 2026-11-19.** The history is kept because the sequence
> matters: 9.2 made the hold visible, and only then could 9.4 state the bug
> precisely.


### Requirement: A script's own log lines MUST reach the agent log

The runner returns the script's `api.log` output as a `logs` array on every tick
response (`agent-script-runner src/main.js:153`), and counts any lines its own cap
dropped in `logs_dropped` (`:154`). The agent SHALL print each returned line to its
own log as `[<bot>/script] log: <line>`, and SHALL print `logs_dropped` when it is
non-zero. A returned log line that reaches the runner's response but not the pod
log MUST NOT be the normal case.

The agent caps what it prints per tick for display (a fixed maximum number of lines
and characters per line). That cap is a flood guard and MUST be reported when it
bites — a silently truncated display is the same defect as a dropped line. It does
NOT replace the runner's own cap (`binding.js:38,41`: 100 lines/min, 1024 bytes per
line), which remains the correctness bound.

#### Scenario: A script's log line appears in the agent log
- **WHEN** the runner answers a tick with `logs: ["hi from scout"]`
- **THEN** the agent log carries a line containing `[<bot>/script] log: hi from scout`

#### Scenario: Lines the runner dropped are visible as dropped
- **WHEN** the runner answers with a non-zero `logs_dropped`
- **THEN** the agent log states how many lines were dropped, so a reader does not
  read silence as the script having logged nothing

#### Scenario: The display cap reports when it bites
- **WHEN** the runner returns more lines than the agent's per-tick display cap
- **THEN** the agent prints the cap's worth and states how many it did not print

> **Why this requirement exists.** M3-1b added a log line to the action gate, and
> on test 2026-11-19 (image `m31b-a26b1c2`, pod `aibot-agent-test-7fc9969694-gxrrg`)
> eight minutes produced ZERO `[Scout/script]` lines of any kind — not the gate's
> line, not a refusal, not a fallback. The line existed in `scout.js` and was being
> executed; the runner returned it in `logs`; nothing on the agent read that field
> (`script_client.py` and `script_tick.py` had no reference to `logs` at all). The
> observability added in M3-1b was therefore invisible in production, and the
> silence that motivated M3-1b reproduced unchanged under a change meant to fix it.
> This is the same shape as M3-1b cause A: a value produced on one side and never
> read on the other.

### Requirement: The tick snapshot MUST reach the script as an envelope

The tick request's `snapshot` field SHALL be the envelope the runner and the scripts
read — an object carrying `tick` and `state`, where `state` holds the bot's facts
(`health`, `food`, `position`, `inventory`, `nearby`, `task`). It SHALL NOT be the
`state` object alone, at any code path.

This MUST hold on EVERY path that builds a snapshot, not only the one with a cache:
`script_tick._build_snapshot` has a cached path returning an envelope and an uncached
path returning a bare state, and a shape that differs by path is a shape the script
cannot rely on.

A bot fact that cannot be read SHALL NOT be presented to the script as an empty
value when the producer answered with an error body. The mod answers an unknown bot
with HTTP 200 and `{"error": "Bot not found: ..."}` (`HttpApiServer.java`, measured
in-pod 2026-11-19), which is not an exception, so the read records no error and the
error body itself becomes the field.

#### Scenario: The script sees the inventory the bot holds
- **WHEN** the bot holds 16 cobblestone and the snapshot is built on the uncached path
- **THEN** `snapshot.state.inventory` in the script is the stack list, and
  the guard does not report the inventory as empty. The game's
  `{"inventory": [...]}` wrapper MUST NOT reach the script: `build_state` unwraps
  it, so every `state.*` observation field is a list on both snapshot paths
  (`a81d5d19`; the wrapper path was tried and reverted)

#### Scenario: Every state field survives both snapshot paths
- **WHEN** a snapshot is built with a cache and without one
- **THEN** both send an envelope whose `state` carries the same keys, and a script
  reading `snapshot.state.<anything>` gets the same answer on either path

#### Scenario: A failed read is not an empty list
- **WHEN** a bot fact read returns an error body rather than a value
- **THEN** the failure is recorded and surfaced, rather than degrading to a default
  that the script reports as "empty"

> **Why this requirement exists.** 9.5's log lines found this on their first run:
> the test pod logged `inventory empty` every ~2 s while Scout held 16 cobblestone.
> `agent.py` builds `ScriptTick` with no cache, so production took the uncached path,
> where `build_state`'s `(state, errors)` tuple was unpacked as if it were
> `(envelope, errors)` — the wire carried a bare state with no `state` key, so every
> `snapshot.state.*` read in the script was `undefined`. The inventory guard was
> only the field loud enough to notice; the health guard and the task read were
> silently blind too. The suite could not catch it because its fake API returned a
> bare list for `inventory`, a shape no producer emits — the M3-1b fixture lesson a
> third time.

### Requirement: Script memory MUST round-trip through the agent

A script's `api.remember(blob)` SHALL be visible to `api.recall()` on the bot's
NEXT tick. The agent MUST send back the `memory_out` the runner returned, per bot,
and MUST build the tick object the way production builds it.

#### Scenario: A remembered value is recalled on the next tick
- **WHEN** a script stores a value with `api.remember` on one tick and the agent
  runs that bot again
- **THEN** the next tick's `api.recall()` returns that value, so a guard keyed on
  it can hold

#### Scenario: Memory reset with the pod
- **WHEN** the agent pod restarts
- **THEN** memory is empty on the first tick, exactly as the tick counter restarts
  at 1, and no guard may assume a remembered value survives a restart

#### Scenario: A tick that does not remember keeps the previous blob
- **WHEN** a script tick succeeds and returns `memory_out` of null because the
  script did not call `api.remember` that tick
- **THEN** the agent keeps the blob from the previous tick rather than replacing
  it with the null, so a guard that stamped a value on an earlier tick still
  reads it back

#### Scenario: A failed tick does not disturb memory
- **WHEN** any runner call falls back (timeout, refused, error)
- **THEN** the agent leaves memory untouched, neither clearing nor advancing it

> **Why this requirement exists.** M3-1 added a store cooldown that stamps the
> tick number through `api.remember("{\"lastStoreAllTick\": n}")`. In production
> that stamp was never read back, so `api.recall()` returned null on every tick
> and the cooldown never engaged: measured on test 2026-11-19, every idle tick
> would have proposed a store. The chain, each link at source:
> `agent.py` constructs `ScriptTick(api, self.name, source)` with no `memory=`, so
> `script_tick.py:284` sent `"memory": None`; the runner maps a non-string to null
> (`main.js:211`), `decodeMemory(null)` returns null (`engine.js:1056-1061`) and
> `recall()` returns it (`binding.js:294`); and `ScriptResult.__slots__` held only
> `state, actions, detail`, so `memory_out` was parsed off the response and
> discarded.
>
> **The suite was green over a round-trip that did not exist.** The test driver fed
> `memoryOut` back into the next tick by hand, which production never did. That is
> the fixture-must-come-from-the-producer failure this file records elsewhere: a
> harness that wires a path the product does not wire cannot fail. The cause-A tests
> below build the tick through the SAME constructor and the SAME client call
> production uses, so an empty round-trip is visible.
>
> **Memory is per-process, like the tick counter.** The agent holds it in memory
> keyed by bot and nothing persists it, so a pod restart empties it at the moment
> `snapshot.py:135` restarts the tick at 1. A remembered tick number from before a
> restart can never be compared against a tick after it, which is why both reset
> together and why no guard may treat a surviving stamp as meaningful.
>
> **A null `memory_out` has two different meanings, and conflating them broke the
> cooldown.** The runner returns null both when a call FELL BACK and when a
> SUCCESSFUL tick simply chose not to call `api.remember`: `memoryOut` is set only
> by that call (`binding.js:314`) and reset to null at the top of every tick
> (`:113`). M3-1b's fix assigned `self._memory = result.memory` on every SCRIPT
> state, which correctly protected a good blob from a fallback and incorrectly
> let a quiet tick erase it. Measured through the real engine: store -> cool ->
> `memory_out` null -> store again, one store every two ticks. The cooldown never
> held, and STORE_ALL fired every ~4 s. The two cases are now distinguished by
> the STATE, not by the null: a fallback leaves memory untouched, and a SCRIPT
> state with a null keeps the previous blob.
>
> **This prevents the AGENT erasing the blob; it does not prevent a SCRIPT from
> clearing its own memory, and the two must not be conflated.** A script cannot
> write `null`: `api.remember` rejects a non-string at `binding.js:298-299`
> before the only non-null assignment at `:314` (`null` and `undefined` both
> return `{ok: false, reason: bad_shape}`). But `api.remember("")` IS accepted -- an
> empty string passes the type check and the byte limit -- so a script CAN
> overwrite its blob with an empty remember, and the carry assigns it. That is
> not a regression and `scout.js:125` is unaffected, because
> `JSON.parse(api.recall() || "{}")` treats `""` as falsy exactly as it treats a
> null. A future reader should read the carry as protecting the agent's copy of
> the blob across a tick that returned nothing, not as making script memory
> read-only.

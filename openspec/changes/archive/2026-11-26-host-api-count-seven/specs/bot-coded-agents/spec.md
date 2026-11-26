## MODIFIED Requirements

### Requirement: The Planner MAY Author A Script As The Plan For A Goal

While planning a world goal, the L3 planner MAY produce a **script** as its
plan — a program that, run once per tick, drives the bot toward the goal —
instead of, or in addition to, a list of directives.

A script the planner authors MUST satisfy every existing authoring constraint in
this capability: it is LLM-only (players MUST NOT supply source), it is
validated before it is stored or bound (see "Authoring Rejects Code That Cannot
Run"), and once bound it runs only through the seven-method `api` surface inside
the sandbox. This requirement adds a *producer* of scripts; it does not relax
any constraint on what a script may do.

A planner-authored script is addressed to exactly one goal. Its identity as
"the script for goal G" MUST be carried wherever a bound script's identity is
carried, so that the M3-1g resume rule can tell "the script for the goal that
finished" from any other script.

#### Scenario: The planner emits a script for a goal
- **GIVEN** a world goal that needs conditional, multi-step logic
- **WHEN** the planner plans the goal
- **THEN** the plan MAY be a script, and if it is, the script is validated and
  bound by the rules of this capability before any tick runs it

#### Scenario: A planner-authored script cannot do more than a hand-written one
- **GIVEN** a planner-authored script
- **WHEN** it runs
- **THEN** it reaches the world only through the seven `api` methods, under the
  same source-size, host-call and sandbox limits as any other script

#### Scenario: A player still cannot supply source
- **WHEN** a player sends text that looks like a script
- **THEN** it is treated as a goal, never as script source to store or run

### Requirement: A Written Script MUST Pass A Dry Tick Before It Is Bound

Validating that a proposal parses and names only known actions is necessary but
not sufficient before binding it to a live bot. A script can be syntactically
valid and still fail its first real tick: it can throw immediately, exceed the
8-host-call-per-tick budget on its first tick, or loop past the per-tick CPU
budget.

Before a planner-authored script is bound to a bot, the system MUST run it once
as a **dry tick** against the bot's current snapshot, with its actions
suppressed (queued actions are discarded, not dispatched), and bind it only if
that tick returns `ok`.

**Binding here is a REBIND, and the requirement names the mechanism.** Today a
bot's script is resolved once for the process lifetime: `_get_script_tick`
reads `bindings.json` on first call and a `_script_loaded` latch
(`agent/agent.py:3213-3215`, set `False` at `:235`) returns the cached tick on
every later call. There is one production caller (`:2916`). An implementer who
calls the existing path to "bind" a written script reaches the latch and gets
the PREVIOUS script for the life of the process. The latch MUST therefore gain
a defined reset for a planner-authored script, and that reset MUST be the only
writer that clears it. Without that reset this requirement is unimplementable;
with it, every other requirement here is ordinary work.

**A dry tick MUST NOT consume the bot's rate budget.** Actions cost nothing to
*discard* — `api.do` pushes onto a sandbox-local array (`binding.js:342-346`)
that the agent throws away — but `acceptAction` records the call in
`botState.actionTimes` (`binding.js:214-216`), which is per-BOT state that
deliberately survives a tick (`binding.js:111-118`, `resetTickState` does not
touch it). The budgets are `do:30/min`, `say:30/min`, `send:20/min`
(`binding.js:96`). A dry tick that spends up to 8 `do` slots for a script that
is then rejected takes those slots from the bot's real work. The dry tick MUST
spend no rate budget: neither `actionTimes` nor `logTimes` may be changed by it.
Both live on the same `createBotState` object (`binding.js:111-118`) and both
survive a tick for the same reason; `api.log` spends `logTimes` exactly as
`api.do` spends `actionTimes` (`binding.js:459-466`), and `log` is one of the
seven `api` methods.

The mechanism that satisfies this is that the dry tick runs against a
**throwaway `botState`**, not the bot's live one. `createApi` already takes
`botState` as a parameter (`binding.js:192-195`); the engine passes its
long-lived object (`engine.js:851-853`) and the default exists only so a direct
caller gets sane behaviour. A dry tick passes its own, so it neither reads nor
writes the live window. This is deliberate, not incidental: `acceptAction`
(`binding.js:214-216`) always either rejects or pushes, with no
check-without-spending mode, so a dry tick sharing the live window could only
avoid spending by never calling `api.do` — which would defeat the gate.

The throwaway state is created **inside the runner**, not by the agent. The
agent does not execute the script: it sends it to the runner service, and
`botState` lives in that process, one long-lived object per cached bot worker
(`engine.js:254` creates it, `:853` passes it every tick, and the `#ensure`
lookup at `fleet.js:166` reuses the worker across requests). A caller
therefore cannot hand in a
`botState` over the wire. The runner request MUST carry an explicit **dry
flag**; when it is set, the runner evaluates the tick against a throwaway
`botState` of its own and never reads or writes the worker's live one. The flag
MUST default to off so every existing caller keeps the present behaviour
unchanged, and a dry request MUST NOT replace or reset the worker's live state.
This is what makes "spends no rate budget" achievable rather than merely
stated: without the flag the requirement is not implementable, because no
request the agent can send reaches the state the requirement protects.

**A dry tick MUST NOT carry its memory forward.** `api.remember` writes
per-tick `state.memoryOut` (`binding.js:436`), so the sandbox write is
naturally discarded — but `script_tick.py:387` adopts the returned memory
(`self._memory = result.memory`), so the hazard is downstream of the sandbox,
not inside it. The dry tick's returned memory MUST be discarded rather than
adopted.

A script that fails its dry tick MUST NOT be bound. The goal MUST fall back to
the plain planner, and the bot MUST keep any previously bound script in force
per "Authoring Rejects Code That Cannot Run" — a failed dry tick disarms
nothing, interrupts no task, spends no rate budget and carries no memory.

#### Scenario: A script that fails its first tick is not bound
- **GIVEN** a planner-authored script that parses but throws on its first tick
- **WHEN** it is dry-ticked against the bot's snapshot
- **THEN** the dry tick returns a non-`ok` outcome
- **AND** the script is not bound, and the goal proceeds through the plain
  planner

#### Scenario: A dry tick dispatches no action
- **GIVEN** a planner-authored script that would emit `api.do` on its first tick
- **WHEN** it is dry-ticked
- **THEN** the queued action is discarded, not dispatched
- **AND** the world is unchanged by the dry tick

#### Scenario: A dry tick spends no rate budget
- **GIVEN** a bot whose `do` rate window already holds entries
- **WHEN** a planner-authored script that calls `api.do` is dry-ticked
- **THEN** the dry tick evaluates against a rate window of its own, not the
  bot's live one (`createApi` takes `botState` as a parameter,
  `binding.js:192-195`)
- **AND** the bot's real script keeps its full budget
- **AND** neither `botState.actionTimes` nor `botState.logTimes` is changed by
  the dry tick

A dry tick therefore never reports `rate_limited` on the bot's live budget: it
neither reads nor writes it. This is the stronger guarantee, and it is the only
one the mechanism supports — `acceptAction` (`binding.js:214-216`) has no
check-without-spending mode, so a dry tick sharing the live window could only
be safe by never calling `api.do` at all, which would defeat the gate.

#### Scenario: A request without the dry flag behaves exactly as it does today
- **GIVEN** a runner request that does not set the dry flag
- **WHEN** the runner evaluates it
- **THEN** the tick runs against the worker's live `botState`, as it does now
- **AND** the worker is neither replaced nor discarded by the request
- **AND** every existing caller — including services that predate this change
  and share the runner — sees byte-identical behaviour

#### Scenario: A dry tick is unaffected by the bot's spent budget
- **GIVEN** a bot whose `do` window is at its 30/min limit
- **WHEN** a planner-authored script that calls `api.do` is dry-ticked
- **THEN** the dry tick is NOT rejected as `rate_limited`
- **AND** it passes or fails on its own merits (throw, host-call cap, CPU)
- **AND** the bot's live `actionTimes` is still unchanged afterwards

#### Scenario: A dry tick carries no memory
- **GIVEN** a planner-authored script that calls `api.remember`
- **WHEN** it is dry-ticked and then rejected
- **THEN** the bot's memory is what it was before the dry tick

#### Scenario: A passing dry tick rebinds a previously written script
- **GIVEN** a bot whose running script THIS agent authored in this process
- **AND** `bindings.json` names no script for this bot
- **AND** a planner-authored script that returns `ok` and queues at least one action
- **WHEN** the written script is dry-ticked and passes
- **THEN** condition 2 holds, because the hand-written file names no script
- **AND** the `_script_loaded` latch is reset by the one writer that clears it
- **AND** the next real tick runs the newly written source, not the previous one

#### Scenario: A failed dry tick does not disarm a working bot
- **GIVEN** a bot already running a valid script
- **WHEN** a new planner-authored script fails its dry tick
- **THEN** the bot continues running its previous script
- **AND** the `_script_loaded` latch is NOT reset
- **AND** no tick is missed

### Requirement: The Script Prompt Names The Host API The Sandbox Binds

A planner-authored script runs in a sandbox whose host API is a fixed surface.
The prompt that asks for the script MUST name that surface, and MUST NOT name
a method the sandbox does not bind: a model that follows the prompt exactly
then writes a call that throws, and the failure surfaces later as an opaque
`script_error` at the dry gate rather than as a prompt defect.

At 2026-11-26 the sandbox binds exactly `do`, `say`, `send`, `recall`,
`result`, `remember`, `log` (`agent-script-runner/src/binding.js:327-496`, the
`api` object `createApi` returns; `result` is at `:412`). The bot snapshot is
a read-only global named `snapshot` (`engine.js:737-850`,
`#installSnapshot`), not an `api` method. The proposal's own dry-tick check
still answers to `validate_proposal`; the prompt's API section MUST agree with
the binding. Every `binding.js`, `engine.js` and `fleet.js` cite in this
requirement was checked against runner `b48c4ad`, so a reader can
re-derive them instead of trusting this date.

#### Scenario: The prompt's API list matches the sandbox's binding
- **GIVEN** the script prompt shipped in `_SCRIPT_SYSTEM_PROMPT`
- **AND** the host API the runner binds
- **WHEN** both lists are compared
- **THEN** every method the prompt names is bound by the runner
- **AND** every method the runner binds is named by the prompt
- **AND** the prompt names `snapshot` as a global rather than an `api` method

#### Scenario: A prompt naming an unbound method is a defect, not a model failure
- **GIVEN** a prompt that instructs the model to call `api.get_snapshot()`
- **AND** a sandbox that binds no such method
- **WHEN** the model follows the prompt
- **THEN** the resulting dry-tick failure is a prompt defect
- **AND** the prompt is what MUST change

### Requirement: A Planner-Written Script's Source Is Logged When It Binds

When the agent binds a script the planner wrote, it MUST log that script's
source once, at the moment of binding, so a trial's behaviour can be read from
the log instead of reconstructed. Trial 4.1 could not be diagnosed because the
agent never logged the source: a script reported "no shears in inventory" while
the bot held shears, and there was no way to tell from the log which field the
script had read.

The log entry MUST carry the bot's name and a hash of the source, so two binds
of the same script are recognisable and two different scripts are
distinguishable. The source MUST be capped at about 4 KiB with an explicit
truncation marker, because a script is bounded at 64 KiB and a log line must
stay readable.

This applies to **planner-written** scripts only. A hand-written binding read
from `bindings.json` MUST NOT be logged by this path: a human put that file
there and can read it. Nothing from the snapshot, the bot's memory, or
`api.remember` output is logged -- only the script source the planner emitted.

Script source carries no secret. It is a program over the seven host calls and
`look`; it cannot contain a credential, because the sandbox has no filesystem,
no network, and no environment access (`engine.js:2-12`). The only values it
can name are action kinds, item ids and literals the model wrote. Logging it
therefore leaks nothing that the planner prompt did not already determine.

#### Scenario: A bound planner script is identifiable in the log
- **GIVEN** a planner reply carrying a script that passes the dry tick
- **WHEN** the agent binds it
- **THEN** the log carries the bot name, a hash of the source, and the source
  itself, in one entry

#### Scenario: A long script is capped, not dropped
- **GIVEN** a planner script longer than 4 KiB
- **WHEN** it binds
- **THEN** the logged source is cut at the cap with a truncation marker saying
  it was cut, so a reader can tell a short script from a clipped one

#### Scenario: A hand-written binding is not logged by this path
- **GIVEN** a bot whose script comes from `bindings.json`
- **WHEN** that script is loaded
- **THEN** this logging path MUST NOT emit its source, because the file is the
  record a human already keeps


## ADDED Requirements

### Requirement: The Planner MAY Author A Script As The Plan For A Goal

While planning a world goal, the L3 planner MAY produce a **script** as its
plan — a program that, run once per tick, drives the bot toward the goal —
instead of, or in addition to, a list of directives.

A script the planner authors MUST satisfy every existing authoring constraint in
this capability: it is LLM-only (players MUST NOT supply source), it is
validated before it is stored or bound (see "Authoring Rejects Code That Cannot
Run"), and once bound it runs only through the six-method `api` surface inside
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
- **THEN** it reaches the world only through the six `api` methods, under the
  same source-size, host-call and sandbox limits as any other script

#### Scenario: A player still cannot supply source
- **WHEN** a player sends text that looks like a script
- **THEN** it is treated as a goal, never as script source to store or run

### Requirement: A Planner-Authored Script Lives In Memory, Not On Disk

**The planner's script output is the step (a) feature, and the planner gains a
script output kind to produce it.** This is a change to the planner's return
contract and its prompt (`agent/planner.py`), not a caller the agent can wire
around: `decompose` and `orchestrate` return a list of step strings today, and
neither type nor prompt has a slot for a program.

A planner-authored script MUST be carried **in the process** as source text and
built into a `ScriptTick` directly. It MUST NOT be written to any file.

This is forced by the capability's own constraint, not chosen for convenience:
`scripts_dir` is a `SCRIPTS_DIR` mount (`agent.py:3111`) and the agent's only
accesses to it are reading `bindings.json` (`:3116`) and joining a resolved
filename (`:3140`) — **there is no write path for script source in the agent
at all.** An in-memory script is the only form that exists inside that
boundary, and it needs no new storage.

`bindings.json` therefore keeps one meaning only: **the hand-written
baseline.** The agent never adds an entry to it, so the file stays exactly the
set of scripts a human deployed, and "hand-written" is decided by that file
alone rather than by provenance the process would have to remember.

#### Scenario: A planner script is never written to disk
- **GIVEN** a planner that emits a script for a goal
- **WHEN** the script is validated, dry-ticked and bound
- **THEN** its source is held in memory and passed to the runner as the tick's
  source
- **AND** no file is created or modified under `scripts_dir`
- **AND** `bindings.json` is unchanged

#### Scenario: A restart returns the bot to its ConfigMap binding
- **GIVEN** a bot running a planner-authored, in-memory script
- **WHEN** the agent process restarts
- **THEN** the in-memory script is gone
- **AND** the bot falls back to whatever `bindings.json` names for it, which is
  a hand-written script if one is deployed there, else to the plain planner
- **AND** no error is raised and no tick is missed during the fallback

#### Scenario: A planner script does not outlive the process that made it
- **GIVEN** a script the planner authored in an earlier process
- **WHEN** the process restarts
- **THEN** there is no artefact to reload it from
- **AND** the change to the bot's behaviour is visibly lost, not silently
  preserved

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
(`agent/agent.py:3206-3208`, set `False` at `:235`) returns the cached tick on
every later call. There is one production caller (`:2909`). An implementer who
calls the existing path to "bind" a written script reaches the latch and gets
the PREVIOUS script for the life of the process. The latch MUST therefore gain
a defined reset for a planner-authored script, and that reset MUST be the only
writer that clears it. Without that reset this requirement is unimplementable;
with it, every other requirement here is ordinary work.

**A dry tick MUST NOT consume the bot's rate budget.** Actions cost nothing to
*discard* — `api.do` pushes onto a sandbox-local array (`binding.js:244-251`)
that the agent throws away — but `acceptAction` records the call in
`botState.actionTimes` (`binding.js:154-174`), which is per-BOT state that
deliberately survives a tick (`binding.js:45-52`, `resetTickState` does not
touch it). The budgets are `do:30/min`, `say:30/min`, `send:20/min`
(`binding.js:44`). A dry tick that spends up to 8 `do` slots for a script that
is then rejected takes those slots from the bot's real work. The dry tick MUST
spend no rate budget: neither `actionTimes` nor `logTimes` may be changed by it.
Both live on the same `createBotState` object (`binding.js:59-65`) and both
survive a tick for the same reason; `api.log` spends `logTimes` exactly as
`api.do` spends `actionTimes` (`binding.js:337-346`), and `log` is one of the
six `api` methods.

The mechanism that satisfies this is that the dry tick runs against a
**throwaway `botState`**, not the bot's live one. `createApi` already takes
`botState` as a parameter (`binding.js:126-136`); the engine passes its
long-lived object (`engine.js:756`) and the default exists only so a direct
caller gets sane behaviour. A dry tick passes its own, so it neither reads nor
writes the live window. This is deliberate, not incidental: `acceptAction`
(`binding.js:154-174`) always either rejects or pushes, with no
check-without-spending mode, so a dry tick sharing the live window could only
avoid spending by never calling `api.do` — which would defeat the gate.

The throwaway state is created **inside the runner**, not by the agent. The
agent does not execute the script: it sends it to the runner service, and
`botState` lives in that process, one long-lived object per cached bot worker
(`engine.js:238` creates it, `:756` passes it every tick, and `fleet.js:166`
reuses the worker across requests). A caller therefore cannot hand in a
`botState` over the wire. The runner request MUST carry an explicit **dry
flag**; when it is set, the runner evaluates the tick against a throwaway
`botState` of its own and never reads or writes the worker's live one. The flag
MUST default to off so every existing caller keeps the present behaviour
unchanged, and a dry request MUST NOT replace or reset the worker's live state.
This is what makes "spends no rate budget" achievable rather than merely
stated: without the flag the requirement is not implementable, because no
request the agent can send reaches the state the requirement protects.

**A dry tick MUST NOT carry its memory forward.** `api.remember` writes
per-tick `state.memoryOut` (`binding.js:314`), so the sandbox write is
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
  `binding.js:126-136`)
- **AND** the bot's real script keeps its full budget
- **AND** neither `botState.actionTimes` nor `botState.logTimes` is changed by
  the dry tick

A dry tick therefore never reports `rate_limited` on the bot's live budget: it
neither reads nor writes it. This is the stronger guarantee, and it is the only
one the mechanism supports — `acceptAction` (`binding.js:154-174`) has no
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

### Requirement: The Agent Decides Script Vs Plain Planner By Stated Conditions

The plain planner MUST remain the default. A planner-authored script MUST be
used for a goal only when all of the following hold, and the decision MUST NOT
be left to the model's preference:

1. The goal is a planning kind the planner may script — a world goal, not a
   single directive, and not a chat/query the planner answers directly.
2. No **hand-written** script is currently bound to this bot. A script this
   agent itself authored in this process is NOT hand-written for this purpose:
   it lives in memory and never enters `bindings.json`, so it fails to make the
   file name a script for this bot. A written script that passes its dry tick
   MAY therefore displace the agent's own previous script, and MUST NOT
   displace a hand-written one.
3. The script passed its dry tick (the preceding requirement).

**Condition 2 is per BOT, not per goal, because that is the binding model.**
`bindings.json` maps bot name to script and the agent reads
`bindings.get(self.name)` (`agent/agent.py:3132`); there is no goal-to-script
association anywhere, so a condition phrased "no script is driving this bot FOR
THIS GOAL" names a relationship the code cannot test and would be vacuously
satisfiable. This does not conflict with the M3-1g hold: the hold records a
`goal_id` (`agent.py:1330-1333`) but suppresses the BOT's dispatch
(`:2901-2904`) — it names the goal that OWNS the pause, not the script the goal
owns. Script identity stays per-goal inside the hold; script ownership stays
per-bot at binding. Those are two different questions and the spec keeps them
apart deliberately.

**"Hand-written" is decided by `bindings.json`, because that file now names
only hand-written scripts.** The bindings file is a flat bot-name-to-filename
map (`{"Scout": "scout.js"}`) and `_bound_script_path` (`agent.py:3070-3121`)
treats the value only as a filename. A planner-authored script is carried in
memory and is never added to this file (see "A Planner-Authored Script Lives In
Memory, Not On Disk"), so an entry here can only have been placed by a human.
Condition 2 asks the only question the code can answer: *does `bindings.json`
name a script for this bot?* A yes is a deliberate human deployment and a
planner MUST NOT overwrite it; a no means the bot is free for a written script
to drive. **A planner script therefore never displaces a hand-written binding.**
The only case in which it replaces a running script is the one the latch reset
exists for: the bot is still on the agent's own previous in-memory script,
which leaves no `bindings.json` entry and so fails condition 2 only when a
human has since deployed one.

**This is what makes the rebind reachable.** Condition 2 gating on ANY bound
script would disable the `_script_loaded` reset in the only case it exists for
— a bot already running a working script. The reset exists precisely so a
written script can replace the agent's earlier one.

**Provenance is PROCESS-SCOPED because the script itself is.** A
planner-authored script lives in memory and is never written to `bindings.json`
(see "A Planner-Authored Script Lives In Memory, Not On Disk"). That file names
only the hand-written baseline, so the question condition 2 asks — *is the
bound script hand-written?* — reduces to *does `bindings.json` name a script for
this bot?* That question is answerable from the file alone, and a script the
agent authored is not in the file.

**This replaces the earlier, severer cost.** The previous draft of this
requirement accepted that an agent-written script would be *frozen* across a
restart: written to the ConfigMap, then permanently indistinguishable from a
human's. That cost is gone. An in-memory script cannot outlive the process that
made it, so a restart does not freeze a stale script — it **drops** it, and the
bot returns to its hand-written binding or the plain planner. The failure mode
is now a lost script, visible as the bot reverting to older behaviour, rather
than a stale script silently outliving the intent that produced it.

The rebind lattice is unchanged in mechanism: a new planner script that passes
its dry tick MUST reset `_script_loaded` so the next real tick runs the new
source. What changes is what sits on the other side of the restart — absence,
not a frozen copy.

If any condition fails, the goal MUST proceed through the plain planner. A
failed or absent script proposal is always a fallback, never a hard error and
never a reason for the bot to idle.

#### Scenario: Plain planner is the default
- **GIVEN** a goal that a single directive can satisfy
- **WHEN** the planner plans it
- **THEN** the plan is directives, and no script is authored or bound

#### Scenario: A goal falls back when the script is not usable
- **GIVEN** a world goal and a planner-authored script that fails its dry tick
- **WHEN** the agent decides script vs plain planner
- **THEN** condition 3 fails and the goal is driven by the plain planner

#### Scenario: A restart drops the script an agent wrote
- **GIVEN** an agent that wrote and bound an in-memory script in an earlier process
- **WHEN** the process restarts
- **THEN** the script is gone, because there is no file it was written to
- **AND** the bot falls back to its `bindings.json` script if one is deployed,
  else to the plain planner
- **AND** the previous script is NOT silently resumed or treated as hand-written

#### Scenario: A hand-written script is not displaced by a new one
- **GIVEN** a bot with a hand-written script currently bound
- **WHEN** the planner proposes a written script that passes its dry tick
- **THEN** condition 2 fails and the hand-written script keeps driving the bot
  until it fails by its own outcome classes or is unbound

#### Scenario: A held script is not resumed by a written-script decision
- **GIVEN** a bot whose script is held by an active chat goal (M3-1g)
- **WHEN** the held goal ends and the script is to resume
- **THEN** an AI-written script resumes by the same rule as a hand-written one,
  with its remembered value intact

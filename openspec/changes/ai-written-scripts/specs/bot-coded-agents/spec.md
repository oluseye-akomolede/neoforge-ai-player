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
(`agent/agent.py:3052-3054`, set `False` at `:235`) returns the cached tick on
every later call. There is one production caller (`:2890`). An implementer who
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
spend no rate budget: `actionTimes` MUST be unchanged by it.

The mechanism that satisfies this is that the dry tick runs against a
**throwaway `botState`**, not the bot's live one. `createApi` already takes
`botState` as a parameter (`binding.js:126-136`); the engine passes its
long-lived object (`engine.js:756`) and the default exists only so a direct
caller gets sane behaviour. A dry tick passes its own, so it neither reads nor
writes the live window. This is deliberate, not incidental: `acceptAction`
(`binding.js:154-174`) always either rejects or pushes, with no
check-without-spending mode, so a dry tick sharing the live window could only
avoid spending by never calling `api.do` — which would defeat the gate.

**A dry tick MUST NOT carry its memory forward.** `api.remember` writes
per-tick `state.memoryOut` (`binding.js:314`), so the sandbox write is
naturally discarded — but `script_tick.py:364` adopts the returned memory
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
- **AND** `botState.actionTimes` is unchanged by the dry tick

A dry tick therefore never reports `rate_limited` on the bot's live budget: it
neither reads nor writes it. This is the stronger guarantee, and it is the only
one the mechanism supports — `acceptAction` (`binding.js:154-174`) has no
check-without-spending mode, so a dry tick sharing the live window could only
be safe by never calling `api.do` at all, which would defeat the gate.

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
- **GIVEN** a bot whose bound script THIS agent wrote and bound in this process
- **AND** a planner-authored script that returns `ok` and queues at least one action
- **WHEN** the written script is dry-ticked and passes
- **THEN** condition 2 holds, because the bound script is not hand-written
- **AND** the `_script_loaded` latch is reset by the one writer that clears it
- **AND** the next real tick runs the written source, not the previous script

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
   agent itself wrote and bound in this process is NOT hand-written for this
   purpose, and a written script that passes its dry tick MAY displace one.
3. The script passed its dry tick (the preceding requirement).

**Condition 2 is per BOT, not per goal, because that is the binding model.**
`bindings.json` maps bot name to script and the agent reads
`bindings.get(self.name)` (`agent/agent.py:3027`); there is no goal-to-script
association anywhere, so a condition phrased "no script is driving this bot FOR
THIS GOAL" names a relationship the code cannot test and would be vacuously
satisfiable. This does not conflict with the M3-1g hold: the hold records a
`goal_id` (`agent.py:1330-1333`) but suppresses the BOT's dispatch
(`:2901-2904`) — it names the goal that OWNS the pause, not the script the goal
owns. Script identity stays per-goal inside the hold; script ownership stays
per-bot at binding. Those are two different questions and the spec keeps them
apart deliberately.

**"Hand-written" MUST be decided by provenance the agent records, not by a
field in `bindings.json`.** The bindings file is a flat bot-name-to-filename
map (`{"Scout": "scout.js"}`) with no provenance field, and
`_bound_script_path` (`agent.py:3027-3035`) treats the value only as a
filename — so a condition reading "no hand-written script is bound" cannot be
evaluated from `bindings.json` at all, and would be as untestable as the
per-goal phrasing it replaces. The agent MUST record, in process, which script
it bound itself. Condition 2 then asks the only question the code can answer:
*did this agent put the bound script here, or did a human?* A hand-written
script is a deliberate deployment and a planner MUST NOT silently overwrite it;
a previously written script is this agent's own prior output and displacing it
is the purpose of this change.

**This is what makes the rebind reachable.** Condition 2 gating on ANY bound
script would disable the `_script_loaded` reset in the only case it exists for
— a bot already running a working script. The reset exists precisely so a
written script can replace the agent's earlier one.

**Provenance is deliberately PROCESS-SCOPED, and this is not an oversight.** The
agent does not write scripts anywhere: `scripts_dir` comes from `SCRIPTS_DIR`
(`agent.py:3006`) and the only accesses are reading `bindings.json` (`:3011`)
and joining the resolved filename (`:3035`) — there is no write path for script
source in the agent at all. That directory is a ConfigMap mount, so it survives
a restart and is shared. The provenance record lives in the process and does
not survive one.

The consequence, stated so that no later implementer "fixes" it into a
`bindings.json` field: **after a restart, an agent-written script is
indistinguishable from a hand-written one and MUST be treated as hand-written,
so it is not displaced.** A fresh process can read the script's bytes but cannot
prove it authored them. A restart is therefore a deliberate deployment
boundary: whatever script is bound after one was placed there by a ConfigMap
change, which is a human action, even when the agent originally generated its
contents.

The cost is accepted and real: a bot that wrote its own script before a restart
cannot replace it after one until a human unbinds it. The alternative — trusting
an authorship claim the process cannot verify — would let a stale script silently
outlive the intent that produced it. A marker written into the stored artefact
is not available to this change, because the agent has no write path to that
artefact; establishing one is the storage design of a later step.

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

#### Scenario: A restart freezes the script an agent wrote
- **GIVEN** an agent that wrote and bound a script in an earlier process
- **WHEN** the process restarts and reloads that same script from `bindings.json`
- **THEN** the fresh process has no record that it authored the script
- **AND** condition 2 treats the script as hand-written
- **AND** the script is not displaced by a new written one until a human unbinds it

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

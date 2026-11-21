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
`scripts_dir` is a `SCRIPTS_DIR` mount (`agent.py:3118`) and the agent's only
accesses to it are reading `bindings.json` (`:3123`) and joining a resolved
filename (`:3147`) — **there is no write path for script source in the agent
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
(`agent/agent.py:3213-3215`, set `False` at `:235`) returns the cached tick on
every later call. There is one production caller (`:2916`). An implementer who
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
long-lived object (`engine.js:783`) and the default exists only so a direct
caller gets sane behaviour. A dry tick passes its own, so it neither reads nor
writes the live window. This is deliberate, not incidental: `acceptAction`
(`binding.js:154-174`) always either rejects or pushes, with no
check-without-spending mode, so a dry tick sharing the live window could only
avoid spending by never calling `api.do` — which would defeat the gate.

The throwaway state is created **inside the runner**, not by the agent. The
agent does not execute the script: it sends it to the runner service, and
`botState` lives in that process, one long-lived object per cached bot worker
(`engine.js:249` creates it, `:783` passes it every tick, and `fleet.js:166`
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
`bindings.get(self.name)` (`agent/agent.py:3139`); there is no goal-to-script
association anywhere, so a condition phrased "no script is driving this bot FOR
THIS GOAL" names a relationship the code cannot test and would be vacuously
satisfiable. This does not conflict with the M3-1g hold: the hold records a
`goal_id` (`agent.py:1349-1352`) but suppresses the BOT's dispatch
(`:2927-2930`) — it names the goal that OWNS the pause, not the script the goal
owns. Script identity stays per-goal inside the hold; script ownership stays
per-bot at binding. Those are two different questions and the spec keeps them
apart deliberately.

**"Hand-written" is decided by `bindings.json`, because that file now names
only hand-written scripts.** The bindings file is a flat bot-name-to-filename
map (`{"Scout": "scout.js"}`) and `_bound_script_path` (`agent.py:3070-3147`)
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

### Requirement: The Script Output Reaches The L3 Goal Path

A player goal is planned by the **L3 orchestrator**
(`plan_orchestrator.execute_task` → `l3_planner.call_plan`), not by
`planner.decompose`. A script output that only the decompose path can produce
is inert for every goal a player actually issues: the deployed agent bound a
script at the decompose branch while three hours of logs showed the orchestrator
running `L3 PLAN`/`L3 EXEC` with zero decompose calls. The script output MUST
therefore be reachable from the path that runs a goal.

**The script is ONE extra OPTIONAL thing on `call_plan`'s reply, carried
outside the plan JSON** (the following paragraphs say exactly where). It is not
a new `kind` and not a new directive type. With no script present the planner's
reply, the resulting `Plan`, and the plan record written by
`trajectory_log.log_call` MUST be byte-identical to what they are today — same
`parsed` object, same `plan_ref` side effects, same subtask list.

**The script MUST NOT appear in any field the DPO trainer reads, and that is
strictly wider than "not in `parsed`".** `build_dpo_dataset.py:89-93` builds
`chosen`/`rejected` from `response_raw` verbatim — the whole reply string, not
the parsed object. `l3_planner.py` passes `response_raw=raw` and
`parsed=data` (`:451`, `:470`), and `trajectory_log.py:90-91` writes both. A
script embedded in the reply JSON would therefore reach the trainer twice:
once through `parsed`, and once more through `response_raw`, which is the field
DPO actually trains on. Guarding `parsed` alone leaves the leak in the field
that matters.

**So the script is not carried inside the reply's JSON at all.** The script
travels in a channel separate from the JSON object the trainer consumes. There
is no parser to hook: `call_plan` reads the model's text inline at
`l3_planner.py:426` (`raw = _strip_codefence(answer_text(resp.json()))`) and
decodes it at `:429` (`json.loads(raw)`), and `raw` is the exact string logged
as `response_raw`. So the channel is a helper this change introduces, called
between those two lines, which splits the script out of the model's text and
returns the plan text alone. `raw` — and therefore `response_raw` and `parsed`
— must then contain no script source, and the two agree because they are
derived from the same cleaned string.

The script channel MUST be separate from the JSON in the model's TEXT, not a
key inside that JSON. A key inside the JSON means the model must escape
arbitrary JavaScript as a JSON string, and a 27B model does not do that
reliably: on test at 15:57Z it emitted a literal newline inside the string and
the whole reply became unparseable, losing a plan that a step list would have
delivered. A fenced block after the JSON — or any delimiter the splitter reads
before `json.loads` runs — keeps a malformed script from costing the plan.

The script MUST NOT be requested in the plan call itself. The plan call keeps
JSON mode and the reply shape it has today, gaining one optional boolean,
`wants_script`. Only when that flag is true does the planner make a SECOND
call, not in JSON mode, asking for the script alone as a fenced block; that
reply is dry-gated like any other. When `wants_script` is false the planner
makes exactly one call, so a step-list goal sees the same mode, the same
prompt rules and the same reply shape as before this change, plus one field.

This supersedes the earlier single-call design, rejected on the trial of
2026-11-20: carrying the script in the same reply forced `format: json` to be
dropped for every plan, putting the common step-list path at risk to serve the
rare scripted one. An extra call on scripted goals only is the smaller cost.

A trainer reading `prompt_system`, `prompt_user`, `response_raw`, `parsed`, or
`world_state_summary` sees exactly what it sees now.

This is the one place the DPO constraint bites hardest, because it rules out
the obvious design: putting the script in the same JSON the plan comes in. The
answer to "where may the script appear in the record" is **nowhere**, and the
mechanism is chosen to make that true by construction rather than by a filter
someone must remember to apply.

A script the planner authors MUST be bound to the bot that runs the goal, by
the rules of this capability ("A Written Script MUST Pass A Dry Tick Before It
Is Bound", "The Agent Decides Script Vs Plain Planner By Stated Conditions"). A
hand-written binding still wins. A script that fails its dry tick is NOT bound
and the goal proceeds on the plan the reply carried, unchanged.

**Paths that author a script, and the ones that do not:**

| Path | Authors a script | Why |
|---|---|---|
| L3 orchestrator, a fresh L3 plan | yes | the goal path a player actually takes |
| Decompose (bot-to-bot messages) | yes, kept | reachable, and tested end to end |
| Plan-template / plan-memory hit | no | reuses a stored plan; there is no planner call to answer with a script |
| Deterministic skill match | no | no planner call |
| Clarify / refuse reply | no | the reply declines to plan |
| Taskboard script answer | yes, kept | already wired and tested |

A plan-template or plan-memory hit takes the Phase 0 return before any planner
call, so it writes no script. That is accepted for now: a repeated goal replays
its stored steps rather than being re-scripted.

#### Scenario: The script is bound on the orchestrator path
- **GIVEN** a bot with no hand-written binding
- **WHEN** a player's goal reaches L3 and the reply carries a script
- **THEN** the agent dry-ticks that script, and on success binds it as the bot's
  in-memory script before the bot's own tick would run it
- **AND** the bot then runs that script rather than the directive plan

#### Scenario: A reply with no script leaves the plan untouched
- **GIVEN** any goal
- **WHEN** the L3 reply carries no script field
- **THEN** the parsed plan object, the subtasks executed, and the record
  `trajectory_log.log_call` writes are exactly those the same reply produces
  today
- **AND** nothing about the plan's shape changes for a trainer reading it

#### Scenario: The script never enters the logged plan
- **GIVEN** an L3 reply that carries both a valid plan and a script
- **WHEN** the planner records the call
- **THEN** the logged `parsed` object contains no script source
- **AND** the logged `response_raw` parses to a JSON object containing no
  script source
- **AND** the script is carried in process memory only

#### Scenario: A step-list goal makes exactly one planner call
- **GIVEN** a goal the planner judges to be a one-shot
- **WHEN** `call_plan` returns with `wants_script` false or absent
- **THEN** the planner makes NO second call
- **AND** the reply is in JSON mode, with the same shape it had before this
  change, so the step-list path is byte-identical apart from the one field

#### Scenario: A malformed script cannot cost a plan
- **GIVEN** a goal the planner judges to be a script candidate, so a second call
  is made for the script alone
- **WHEN** the script reply contains a character illegal raw inside a JSON
  string — a literal newline, a tab, an unescaped quote — which is what a small
  model writing multi-line JavaScript produces
- **THEN** the plan from the first call is already parsed and is untouched
- **AND** a script that cannot be recovered is treated as no script: nothing is
  bound and the goal runs the plan
- **REASON** measured on test, 2026-11-20 15:57Z: the model wrote multi-line JS
  with a literal newline inside the JSON string. The reply was unparseable, so
  a repeating goal that used to get a step list failed outright. Moving the
  script to its own call makes this failure cost the script and nothing else.

#### Scenario: The script channel survives a multi-line quoted script
- **GIVEN** a script with several lines, single and double quotes, and a regex
  or string containing braces
- **WHEN** the second call returns it and the planner extracts it
- **THEN** the script the planner binds is byte-identical to the source the
  model wrote

#### Scenario: No field the trainer reads contains script source
- **GIVEN** a goal for which the planner made both calls
- **WHEN** the plan call is logged
- **THEN** no field `build_dpo_dataset.py` reads — `prompt_user`,
  `response_raw`, `parsed` — contains any of the script's source, which cannot
  reach them: the script arrived in a different call
- **AND** the `chosen` string a trajectory pair would be built from is
  byte-identical to what the same plan without a script would produce
- **AND** the script call is either not logged as a trajectory record at all, or
  is logged in a record whose `parsed` the trainer does not consume as a plan
  pair

#### Scenario: A template hit writes no script
- **GIVEN** a goal that matches a saved plan template
- **WHEN** the orchestrator replays it
- **THEN** no planner call is made, no script is authored, and the template's
  steps run as they do today

### Requirement: The Planner Writes A Script For Repeating Or Conditional Goals

A script output that the planner never chooses is a feature the bots never use.
The planner MUST be given a stated rule for when a script is the right answer,
and that rule MUST be the same in the spec and in the prompt the planner is
sent, so the choice is not left to the model's taste.

**A goal is a script when it repeats, waits on a condition, or reacts over
time.** Those goals have no fixed end, so a list of one-shot steps cannot
express them: it runs out and stops while the goal is still live. Examples:
"keep the furnace fed", "keep the chest stocked", "store items whenever your
inventory fills", "tell me when it gets dark", "until I say stop, mine gravel".

**A goal is a step list when it is a bounded one-shot.** It finishes, and its
success is checkable at the end: "go to X", "craft Y", "bring me 64 stone",
"build a 5x5 shelter here". These MUST stay step lists. A script for a one-shot
goal buys nothing — the plan already ends — and costs the planning and dry-tick
round trip.

The rule MUST NOT override any other constraint in this capability: a goal that
is clearly one-shot stays a step list even if it is phrased with a time
clause, and a script is still subject to the hand-written check and its dry
tick. When a goal could be read either way, the planner MAY choose.

**The choice is visible in the agent's log lines, not in the trajectory
record.** A script answer is distinguishable because the agent emits the
dry-gate and bind lines ("Exactly One Driver Per Goal", which requires the
bind and its handover on the status line), and a step-list answer is
distinguishable because it produces `L3 EXEC` lines. That is where the choice
can be observed. It MUST NOT be made observable by putting the script into the
trajectory record: the previous paragraph forbids that, and the DPO constraint
below is why. An earlier draft of this requirement said the choice was visible
"in the trajectory log today", which was both false (no script field exists)
and in direct conflict with the scenario asserting the script never enters the
logged plan.

#### Scenario: A repeating goal is answered with a script
- **GIVEN** a goal with no fixed end, such as "keep the furnace fed"
- **WHEN** the planner plans it
- **THEN** the reply carries a script, and that script is dry-ticked and bound
  by the rules of this capability

#### Scenario: A conditional goal is answered with a script
- **GIVEN** a goal that waits on or reacts to a condition, such as "store
  items whenever your inventory fills"
- **WHEN** the planner plans it
- **THEN** the reply carries a script

#### Scenario: A one-shot goal stays a step list
- **GIVEN** a bounded goal, such as "go to X" or "craft 8 iron ingots"
- **WHEN** the planner plans it
- **THEN** the reply carries steps and no script
- **AND** no dry tick runs and the plan executes as it does today

#### Scenario: The prompt states the same rule as the spec
- **GIVEN** the prompt the L3 planner is sent
- **WHEN** it is read
- **THEN** it names the repeating/conditional goals as script cases and the
  bounded one-shot goals as step-list cases, and does not leave the choice to
  preference alone

### Requirement: A Goal's Own Script Is Not Held By That Goal

M3-1g holds the bot's running script while a chat goal is planned, so the script
and the goal's planner cannot both act on one intent. That hold covers a script
that was **already bound when the goal arrived**. A script the planner authors
**for this goal** is not a rival to the goal's execution — it IS that execution.
Holding it would suppress the one run the goal asked for, and for a repeating
goal ("keep the furnace fed") nothing would happen until some unrelated path
ended the goal, which for a goal with no fixed end may never come.

**Binding the goal's own script MUST release this goal's hold.** The hold
is released by the `goal_id` that owns it, through the existing release, which
is identity-guarded: a newer goal's hold is never released by an older run's
exit (`_end_script_hold` returns False unless the id matches). The release MUST
be part of the bind, not a separate decision, so there is no window in which the
script is bound and still held.

The order is: a chat goal arrives and sets the hold; its planner returns a
script; the agent dry-ticks it; on success it binds the script and releases
that goal's hold; the bot's next tick dispatches the script's actions. The same
release runs on every terminal path of the run (normal exit, crash, planner
disabled), so a hold cannot outlive the goal that owns it.

A script already bound from an earlier goal, or a hand-written one, is a rival
to this goal and remains held for it exactly as today. When the goal's own
script is bound, the earlier in-memory script is **replaced**, not resumed:
`_bind_planner_script` assigns `self._planner_script = source` (`:3185`), so
the previous source ceases to exist and only the new one runs. The release is
safe precisely BECAUSE the bind replaces it — releasing the hold would otherwise
hand the bot back to a rival script, and it does not, because there is no longer
a rival to hand it to. A hand-written binding is not replaced: it wins, and the
bind is refused before any of this (condition 2), so the hold stands.

#### Scenario: Binding a goal's own script releases that goal's hold
- **GIVEN** a chat goal that has set the M3-1g hold
- **WHEN** the planner for that goal returns a script and it passes its dry tick
- **THEN** the script is bound and that goal's hold is released, in that order
- **AND** the bot's script tick runs the bound script's actions within the next
  few ticks, with no intervening goal needing to end first
- **AND** the released hold names this goal, so a newer goal's hold is not
  released by this bind

#### Scenario: A one-shot goal never reaches the bind
- **GIVEN** a bounded goal that the planner answers with steps
- **WHEN** the plan finishes
- **THEN** no script was bound and the hold is released by the run's normal
  terminal path, as today

#### Scenario: A pre-existing script stays held
- **GIVEN** a bot with a bound script when a chat goal arrives
- **WHEN** the planner for that goal authors no script
- **THEN** the pre-existing script stays held for that goal, as today

### Requirement: Exactly One Driver Per Goal
After the goal's own script is bound and its hold released, one thing drives the
bot and only one. If the script is bound, the orchestrator MUST NOT go on to
execute the step list from the same `call_plan` reply, and the goal MUST close
as handed over to the script, recording that on its status line in the log. A
reply that both binds a script and executes its own steps would put the script's
ticks and the L3 execution loop in competition, issuing directives against the
same bot at the same time.

**This is the same trap as the hold, one layer up.** The hold releases because
the script now drives the goal. If the orchestrator keeps stepping as well, then
releasing the hold has not handed over control — it has duplicated it. The two
requirements are one mechanism and MUST be implemented together: release the
hold *because* nothing else drives, and stop driving *because* the script does.

**The step list in a script reply is not wasted, but it is not executed.**
This requirement constrains execution, not what may be recorded. What the
recorded plan may contain is fixed by the DPO requirement: nothing a planner
script touches may enter a record the trainer reads.

**A reply with no script is untouched.** With no script, the orchestrator
executes the reply's steps exactly as it does today, including the log lines
that record them.

#### Scenario: A script reply means no L3 execution for that goal
- **GIVEN** a chat goal to a bot with no hand-written binding
- **WHEN** `call_plan` replies with a script and that script passes its dry tick
- **THEN** the script is bound and the goal's hold released
- **AND** no `L3 EXEC` lines are logged for that goal after the bind
- **AND** the goal closes as handed to the script, said plainly on its status
  line in the log

#### Scenario: A reply without a script still executes its steps
- **GIVEN** a chat goal to a bot with no hand-written binding
- **WHEN** `call_plan` replies with steps and no script
- **THEN** the orchestrator executes those steps as it does today
- **AND** the `L3 EXEC` lines for the goal appear as they do today

#### Scenario: A failed dry tick leaves the orchestrator in charge
- **GIVEN** a `call_plan` reply that carries a script
- **WHEN** that script fails its dry tick
- **THEN** nothing is bound and this path releases no hold
- **AND** the orchestrator executes the reply's steps, so the goal is still
  driven by exactly one thing

### Requirement: A Script That Never Dispatches Anything Yields The Goal

"Exactly One Driver Per Goal" says what happens when a script *takes* a goal.
This requirement covers a driver that has taken the goal and can never act on it.

When every action a script proposes in a tick is refused by the binding,
`_run_script_tick` returns `False` and the caller falls through to the planner
(`agent/agent.py:3230`). That fall-through does not hand the goal back. The
script stays bound, and the planner is not asked for a new one: `_plan_steps`
still holds the steps from the reply that carried the script, and
`_check_task_board` is skipped because that list is non-empty. The loop then
repeats identically on the next tick.

Trial 4.1 measured it at 2026-11-21 22:25Z: 69 refusals, 69 "falling back to
planner" lines, 1 L3 SCRIPT call, 0 new plans, over six minutes, for a goal
whose only action was an unknown kind. The log said the agent was falling back.
Nothing was.

An all-refused tick MUST do one of two things, and the implementation MUST
state which in the log:

1. **Yield the goal.** Unbind the script and hand the goal back so `call_plan`
   is asked again. Preferred, because the goal is still pursued and the
   refusals are the signal that the script was wrong.
2. **Stop and report.** After N consecutive all-refused ticks, unbind the script
   and say why in chat and in the log.

Silently rerunning a script that cannot dispatch is neither. The counter MUST be
consecutive: a tick that dispatches something resets it, so a script that
intermittently succeeds is never torn down.

Option 1 is the shipped behaviour for this change. It is recorded here as a
permanent choice rather than a dated one: the goal is pursued either way, and
option 2 leaves the bot idle on a goal a planner could have taken. Option 2
remains the stated alternative for a future implementation that has a reason to
prefer stopping.

`N` is not fixed by this requirement, because the useful value depends on tick
length and on how often a script is expected to be transiently refused. It MUST
be a single named constant rather than a literal at the comparison, and the
implementation MUST record the observation that chose it. The measured failure
that prompted this requirement ran 69 consecutive refusals, so any `N` below
about 30 would have fired; a small value risks tearing down a script that was
about to dispatch.

#### Scenario: A script whose only action is refused stops being the driver

- **GIVEN** a bound script whose only action is an unknown kind
- **WHEN** a tick refuses every action it proposes
- **THEN** the bot is no longer running that script
- **AND** the reason is visible in the log
- **AND** the goal is not left with no driver

#### Scenario: A tick that dispatches resets the refusal count
- **GIVEN** a script that refuses every action on some ticks and dispatches one
  on others
- **WHEN** the refusals never reach N in a row
- **THEN** the script stays bound

### Requirement: Binding A Script Is Atomic Against The Bot's Tick
Binding happens on the orchestrator's thread while the bot's own tick loop is
running on another, and the bind touches state the tick reads. `_bind_planner_script`
(`agent.py:3149-3196`) assigns `_planner_script`, clears `_script_tick`, and
sets `_script_loaded = False` — three fields `_get_script_tick` consults to
decide what to run. `_run_script_tick` (`agent.py:2895-2930`) takes no lock on
that path. Interleaved with a tick, the tick can observe the new source with the
old cached `ScriptTick`, or a cleared latch with the old source, and dispatch
against neither the old script nor the new one.

The bind and the reset it depends on MUST be atomic with respect to a script
tick: a tick sees either the whole previous state or the whole new one, never a
mix. `self._lock` already exists (`agent.py:274`) and is the lock to use, but
this requirement is about the guarantee, not the primitive — a lock, an atomic
swap, or making the three assignments one object replacement all satisfy it.

**This is why the requirement lives here rather than in the implementation
notes.** The delta forces the bind to happen while the bot is live: the hold is
released as part of the bind so the script's ticks start immediately ("A Goal's
Own Script Is Not Held By That Goal"). Making the bind overlap the tick is a
direct consequence of that requirement, so the safety property it needs belongs
in the same delta, not in a reviewer's head.

#### Scenario: A tick never sees a half-applied bind
- **GIVEN** a bot whose tick loop is running against its current script
- **WHEN** a planner script is bound concurrently
- **THEN** any tick observes either the previous script and latch together, or
  the new script and its reset latch together
- **AND** no tick dispatches against a source it did not fully load

#### Scenario: A dry tick inside the bind does not race the live tick
- **GIVEN** a bind in progress that is running its dry tick
- **WHEN** the bot's own tick fires
- **THEN** the bot's tick either waits for the bind to finish or sees the
  pre-bind state in full
- **AND** the dry tick's throwaway state never becomes the bot's live state


### Requirement: The Script Call's Token Budget Fits A Whole Script

The SCRIPT call SHALL be given a token budget large enough to hold the whole
reply it is asked for. The budget MUST NOT be one that a correct answer can
exceed, because a reply that runs out of tokens is not a shorter script: the
fence is left unclosed, extraction finds no block, and the goal silently falls
back to its step list.

A truncated reply MUST remain "no script" rather than a partially-bound
program. Raising the budget does not make truncation safe; it makes it rare.
The two properties are separate and both are required: room to answer, and a
refusal to use an answer that was cut short.

#### Scenario: A script longer than the old budget is returned whole

- **GIVEN** a repeating goal whose script is longer than the call's previous
  token budget
- **WHEN** the SCRIPT call runs
- **THEN** the reply MUST NOT stop for length
- **AND** the script MUST be extracted and reach the dry gate

#### Scenario: A reply that does stop for length binds nothing

- **GIVEN** a SCRIPT call that stops with `done_reason: "length"`
- **WHEN** the reply is processed
- **THEN** the call MUST yield no script
- **AND** the goal MUST proceed on its plan's step list
- **AND** the log MUST name truncation as the cause, distinct from a malformed
  or missing fence

#### Scenario: A truncated reply holding a complete-looking block still binds nothing

- **GIVEN** a SCRIPT call whose reply stops with `done_reason: "length"` and
  whose content already contains a js fence that closes before the cut
- **WHEN** the reply is processed
- **THEN** the call MUST yield no script
- **AND** the block MUST NOT reach the dry gate or the bind
- **AND** extraction MUST NOT be consulted to decide this

The model can close a fence and keep writing; a cut after that fence leaves a
block that parses. Deciding on the reply's own report of why it stopped is the
only check that does not depend on where the cut landed.

#### Scenario: The plan call keeps its own budget when the script call's changes

- **GIVEN** the SCRIPT call is configured with a token budget different from
  the plan call's
- **WHEN** a goal's plan call is made
- **THEN** the plan call's request MUST carry `num_predict` 1024
- **AND** it MUST NOT carry the script call's budget

The subject is the plan call's outgoing request: a test reads `num_predict`
off what the plan call actually sent and fails if it is anything but 1024.
Stating it as "a change to one must not change the other" named no request to
inspect, so nothing could falsify it.

### Requirement: One Rule Decides What Closes A Script Block

The extractor and the warning that describes it MUST read the same fence rule,
and the rule MUST accept a script the model has finished writing. Two
definitions of a closing fence is how a reply gets reported "unusable" while
being extractable, or the reverse: the warning names a cause the extractor
never acted on.

A closing fence MUST end the script even when the model writes more text after
it on the same line, because the script was already complete at the fence. What
the model adds afterwards is commentary, not code. Rejecting that reply discards
a whole correct program over a sentence.

The rule MUST NOT accept as a script a block that never closed, and MUST NOT
treat a fence belonging to a non-js block as closing a js one.

#### Scenario: A closing fence followed by prose on its line still yields the script

- **GIVEN** a SCRIPT reply containing a js block whose closing fence is
  followed on the same line by explanatory text
- **WHEN** the reply is extracted
- **THEN** the script MUST be the js block's body
- **AND** the trailing text MUST NOT be part of it
- **AND** the warning MUST NOT report a missing closing fence

#### Scenario: A block that never closed is not a script

- **GIVEN** a SCRIPT reply whose js fence is never closed
- **WHEN** the reply is extracted
- **THEN** extraction MUST yield no script
- **AND** the warning MUST name a missing closing fence
- **AND** that holds however many fences appear before the js one

### Requirement: A Script Failure Names Its Own Cause

A dry tick that fails MUST say why. The trial of 2026-11-20 21:2xZ reached the
dry gate and logged `script_error` with no further detail: the runner sends a
`message` on every error (`agent-script-runner/src/main.js`), and
`agent/script_client.py:204` kept only `error_class`, so the reason the runner
supplied was discarded on our side.

A bare `script_error` covers every exception a script throws, because the
runner's `normaliseError` maps all of them to that one kind (only stack
overflow, CPU interruption and out-of-memory are split out). So a call to an
unbound method, an unclosed brace, and a write to a frozen global all arrive
looking identical until the message is read.

Two facts a reader of the log should not have to rediscover:
- The exception NAME (`TypeError`, `SyntaxError`) is not available to the
  agent. The worker puts `{kind, name, message}` on the wire, but
  `main.js:242` flattens it to `error_class` + `message` and drops `name`.
  The agent therefore MUST NOT be specified against an `error_name` field
  that no runner revision sends.
- The runner reports no line or column for a script error.

The failure record MUST carry the runner's message when the runner sends one,
bounded and escaped so a multi-line message cannot forge extra log lines. The
record MUST also carry a bounded head-and-tail preview of the script source
that failed, because the defect is usually at one end of the program and a
head-only preview cuts the tail where it often lives.

The preview is model-authored content and MUST be logged ONLY. It MUST NOT be
written to memory, to a bound script, or to any field the DPO trainer reads.

#### Scenario: A runner error keeps the message the runner gave it
- **GIVEN** a runner that fails a script with `error_class: "TypeError"` and `message: "api.get_snapshot is not a function"`
- **WHEN** the client reports the failure
- **THEN** the detail carries both the class and the message
- **AND** the message is bounded and newline-escaped

#### Scenario: A failed dry tick logs enough to diagnose it offline
- **GIVEN** a planner-authored script that fails its dry tick
- **WHEN** the failure is logged
- **THEN** the log names the error class and the runner's message
- **AND** it includes a bounded head-and-tail preview of the failing source
- **AND** no other log line is forged by that content

### Requirement: The Script Prompt Names The Host API The Sandbox Binds

A planner-authored script runs in a sandbox whose host API is a fixed surface.
The prompt that asks for the script MUST name that surface, and MUST NOT name
a method the sandbox does not bind: a model that follows the prompt exactly
then writes a call that throws, and the failure surfaces later as an opaque
`script_error` at the dry gate rather than as a prompt defect.

At 2026-11-20 the sandbox binds exactly `do`, `say`, `send`, `recall`,
`remember`, `log` (`agent-script-runner/src/binding.js:109-135`). The bot
snapshot is a read-only global named `snapshot` (`engine.js:660-680`), not an
`api` method. The proposal's own dry-tick check still answers to
`validate_proposal`; the prompt's API section MUST agree with the binding.

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

### Requirement: The Script Prompt Names The Action Kinds The Binding Accepts

`api.do(directive, args)` takes an action kind, and the binding layer accepts a
closed set of them. The prompt MUST name that set, and MUST NOT offer an example
kind the binding refuses. This is the same defect as naming an unbound method,
one level down: a model that follows the prompt exactly gets its only action
refused, the script proposes nothing dispatchable, and the tick falls through to
a planner that has no plan for this goal. The bot then reruns the same refused
script every tick -- a visible stall that reads, in the logs, as the agent
working.

The set is `action_binding.BINDABLE_KINDS` -- 45 kinds at 2026-11-21, being
`AGENT_SIDE_KINDS` (10) plus `MOD_DIRECTIVE_KINDS` (35). The prompt's list MUST
be generated from or pinned against that constant by a test, so the two cannot
diverge silently; the same pattern as `test_bindable_set_matches_source`.

The failure is intermittent when the example list is MIXED, and that is why this
survived. The shipped prompt offered four kinds: `goto` and `mine` bind, `attack`
and `place` do not. A uniformly wrong list refuses every attempt and is noticed on
the first run; a list that works for half its examples lets a model that samples
them appear to succeed some of the time, so the trial yields partial progress and
no single failing line. The requirement is therefore that EVERY example be
dispatchable, not that some be, and the test MUST cover each one rather than
asserting membership of the list as a whole.

`bind_action` upper-cases the kind before checking it (`action_binding.py:74`),
so `"mine"`, `"MINE"` and `"Mine"` all bind. The prompt shows lowercase for
readability; it MUST say that case is not significant, because a model writing
`"Mine"` should be told that is fine rather than left to infer it.

#### Scenario: The prompt's action kinds match the binding
- **GIVEN** the script prompt shipped to the planner
- **AND** `action_binding.BINDABLE_KINDS`
- **WHEN** the two are compared
- **THEN** every kind the prompt names as a bare example is in the set
- **AND** a test fails if a kind is added to or removed from the set without the
  prompt changing in the same commit

#### Scenario: Every example kind is dispatchable
- **GIVEN** the prompt's examples for `api.do`
- **WHEN** each example kind is passed to `bind_action`
- **THEN** none raises `RefusedAction`
- **AND** in particular the prompt does not offer `attack` or `place`, which are
  not bindable kinds

#### Scenario: A refused kind reaches the fallback, not a stall

- **GIVEN** a script whose only action is an unknown kind
- **WHEN** a tick refuses every action
- **THEN** the script is unbound and the goal is handed back for `call_plan`,
  not left bound to rerun the identical tick
- **AND** the reason is visible in the log

### Requirement: A Length-Stopped Plan Reply Is Reported As Truncated

When the PLAN call stops because it ran out of tokens, the failure MUST be
reported as truncation, with `done_reason` and `eval_count` in the log. It MUST
NOT be reported as "reply was not JSON".

The two are different facts and only one of them is the model's fault. A reply
cut mid-object is well-formed JSON up to the cut and the model may have been
about to answer correctly; a reply that is not JSON at all is a prompt or model
failure that a bigger budget will not fix. The trial of 2026-11-20 21:52Z
logged `L3 PLAN reply was not JSON (Expecting value: line 3 column 16 (char
92))` for a reply that was a truncated plan, which sends a reader to fix the
prompt.

The same rule already applies to the SCRIPT call, where a length stop means
"no script" before extraction is attempted. `config.answer_text` raises
`TruncatedAnswer` ONLY when the content is empty, so a reply carrying a partial
object never reaches that guard; `call_plan` MUST therefore decide on
`done_reason` itself, before it parses.

The PLAN call's budget MUST be large enough for a normal plan plus whatever
the model emits before it, measured on the deployment rather than guessed. A
plan is a JSON object of several subtasks and is larger than the script call's
one-program reply, which needed 6144.

#### Scenario: A plan cut short by the token limit
- **GIVEN** an Ollama reply with `done_reason: "length"` whose content is a
  JSON object cut mid-way
- **WHEN** the PLAN call processes it
- **THEN** it MUST fail as truncated, naming `done_reason` and `eval_count`
- **AND** it MUST NOT be reported as a non-JSON reply

#### Scenario: A complete plan is unaffected
- **GIVEN** an Ollama reply with `done_reason: "stop"` holding a complete plan
- **WHEN** the PLAN call processes it
- **THEN** the plan MUST be built exactly as before

#### Scenario: The budget was measured against the deployed model
- **GIVEN** the model the agent runs against, asked the real PLAN prompt
- **WHEN** the plan budget is chosen
- **THEN** it MUST exceed the largest `eval_count` observed at a higher budget

### Requirement: A Script's Say And Send Are Delivered, Not Refused

The runner's `api.say` and `api.send` produce action records beside the
`do` records, and the agent MUST deliver them through the paths the planner
already uses rather than refusing them: `say` through the existing chat-send
path, `send` through the existing inter-bot message path. The agent MUST NOT
open a new channel for either, MUST NOT change the runner, its rate limits, or
the set of `do`-dispatchable kinds, and MUST NOT deliver anything from a dry
tick.

A delivered `say` or `send` counts toward the tick having handled it. Before
this, the trial of 2026-11-20 22:21Z (image `e3478fb8`, goal "say all clear in
chat") ran a script every ~61 s that called `api.say` each time, and every call
was refused with "action is a 'say' call, not a dispatchable 'do'". The script
then read as "all actions refused" and fell back to the planner, so nothing was
said in game. The planner prompt offers `api.say` and `api.send`; a planner
script that chats must be able to chat.

The runner's own rates bound this and remain the only bound: `api.say` 30/min
and `api.send` 20/min per bot, enforced inside the runner (contract §8), so a
script that calls them too often is already rate-limited before its records
reach the agent. The agent adds no second limiter on how often a script may
speak: a later content dedupe (change `script-say-dedupe`) suppresses a repeat
of the *same* line within 60 seconds, which bounds repeats of a line, not the
number of *distinct* lines per minute, and so does not bound the rate these
lines arrive at.

One known gap bounds that guarantee: the window lives on the sandbox
(`engine.js:251`, documented at `engine.js:399-406`), so a sandbox recycle
after a `memory_exceeded`, a guard eviction or a wasm trap restarts it empty.
The honest bound is therefore 30 per rolling minute for `say` and 20 for
`send`, plus up to the same amount again per recycle. An ordinary script
throw does not recycle the sandbox (`recycle.js:45-49`).

#### Scenario: A say action is delivered through the chat path
- **GIVEN** a tick whose script called `api.say("all clear")`
- **WHEN** the agent processes the action records
- **THEN** it MUST call the existing chat path once with that text
- **AND** the tick MUST count as handled, not as "all actions refused"

#### Scenario: A send action reaches the other bot
- **GIVEN** a tick whose script called `api.send("Scout", "on my way")`
- **WHEN** the agent processes the action records
- **THEN** it MUST deliver the message through the existing inter-bot path
- **AND** the tick MUST count as handled

#### Scenario: A tick with both a do and a say handles both
- **GIVEN** a tick whose script called `api.do` and `api.say`
- **WHEN** the agent processes the action records
- **THEN** the `do` MUST dispatch as it does today
- **AND** the `say` MUST be delivered
- **AND** neither MUST be refused merely for sharing a tick with the other

#### Scenario: A dry tick delivers nothing
- **GIVEN** a script that calls `api.say` and `api.send`
- **WHEN** it is run under a dry tick
- **THEN** no chat message MUST be sent and no message MUST reach another bot
- **AND** the script's `last_deliveries` MUST be empty
- **AND** the dry tick's question MUST remain "can this script run" only

The runner does not read the dry flag (at `7855a39`, `grep -rn "dry" src/`
finds nothing), so this holds only because the script tick clears
`last_deliveries` when it is dry. That clear MUST be exercised by a test that
drives a **real** dry tick carrying `say`/`send` records, so the records reach
the routing and only the clear can empty them; a test that mocks the script
tick cannot hold this line, because the records it returns are never routed.

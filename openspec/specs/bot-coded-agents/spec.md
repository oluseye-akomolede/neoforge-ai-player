# bot-coded-agents Specification

## Purpose

Define how a bot runs code its own planner wrote, and what that code is allowed
to do to the shared server. Covers the script surface a script may call and the
snapshot it reads, the guarantees that keep a buggy script from speaking twice,
spamming or looping without bound, the metering of code hours per bot, and the
planner-side rules for authoring and repairing a script rather than hand-writing
every step.

## Requirements

### Requirement: A Script's Repeated Line Does Not Reach Chat Twice In A Minute

The agent MUST NOT deliver a script's `say` whose text was delivered by that
bot through the script path within the last 60 seconds, and MUST NOT deliver a
script's `send` whose `(to, text)` pair was so delivered within the last 60
seconds. A suppressed call MUST be counted as suppressed rather than as
delivered, and the agent MUST log at most one line per suppressed key per
60-second window — not one per tick. Nothing MUST replace a suppressed line.

This requirement dedupes repeated *content*; it is not a rate limit, and it is
the content dedupe that the delivered-not-refused requirement above says is not
a second limiter: it does not bound distinct lines per minute. The runner's
per-bot limits (30 `say` and 20 `send` per rolling minute, enforced in the
runner) remain the only bounds on how often a script may speak, and the agent
MUST NOT add a second one. A script that says several *different* things in a
minute is unaffected by this requirement.

The memory is per bot and holds, per key, the time that key was last delivered
and whether its suppression has already been logged for the current window.
Both live in one record per key, so the log-once flag cannot drift from the
suppression window it describes. The memory is held by the agent, not by the
runner and not by the sandbox, so a sandbox recycle does not clear it.

A suppressed call is not a refusal: the tick still counts as handled, and a
script that is being deduped is not treated as though it failed.

#### Scenario: The same line is not delivered twice within a minute
- **GIVEN** a bot whose script delivered `api.say("No diamond ore within 5-block radius.")`
- **WHEN** 10 seconds later the script calls `api.say` with the exact same text
- **THEN** the agent MUST NOT deliver it to chat again
- **AND** it MUST count as suppressed, not delivered

#### Scenario: The window boundary is exclusive at exactly 60 seconds
- **GIVEN** a bot that delivered a `say` with some text at time `T`
- **WHEN** the script says the exact same text at exactly `T + 60.0` seconds
- **THEN** the agent MUST deliver it, because the comparison is `now - then < 60.0`
- **AND** at `T + 59.999` seconds it MUST NOT deliver it

#### Scenario: The same line is delivered again after the window
- **GIVEN** a bot that delivered a `say` with some text
- **WHEN** 61 seconds later the script says the exact same text
- **THEN** the agent MUST deliver it to chat

#### Scenario: A different line is delivered at once
- **GIVEN** a bot that just delivered `api.say("watching for diamond ore")`
- **WHEN** the next tick the script says `api.say("found diamond ore at -42, 12, 87")`
- **THEN** the agent MUST deliver it

#### Scenario: Alternating lines do not defeat the rule
- **GIVEN** a script that alternates `api.say("A")` and `api.say("B")` every tick
- **WHEN** the ticks are 10 seconds apart
- **THEN** each of `A` and `B` MUST be delivered at most once per 60 seconds

#### Scenario: send is deduped per recipient
- **GIVEN** a bot whose script sent `("Scout", "on my way")` 5 seconds ago
- **WHEN** the script sends `("Scout", "on my way")` again
- **THEN** the agent MUST NOT deliver it
- **AND** had the recipient been `"Builder"` with the same text, it MUST deliver it

#### Scenario: A suppression is logged once per window, not once per tick
- **GIVEN** a script that says the same text on every tick for 60 seconds
- **WHEN** the agent suppresses those calls
- **THEN** it MUST log the suppression once for that key in that window, not
  once per suppressed tick

#### Scenario: Dedupe does not become a rate limit
- **GIVEN** a script that says twelve different lines in one minute
- **WHEN** all are within the runner's own limits
- **THEN** the agent MUST deliver all twelve

#### Scenario: Suppression is not a refusal
- **GIVEN** a tick whose only script output is a `say` that was suppressed as a repeat
- **WHEN** the agent processes the tick
- **THEN** the tick MUST still count as handled
- **AND** the script MUST NOT be reported as having its actions refused

#### Scenario: A dry tick neither reads nor writes the memory
- **GIVEN** a bot has delivered a `say`
- **WHEN** a dry tick runs a script saying the same text
- **THEN** the dry tick MUST NOT deliver anything
- **AND** it MUST NOT change what the next live tick is compared against

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

### Requirement: A Script That Never Dispatches Anything Yields The Goal

Trial 4.1's first run measured the failure at 2026-11-21 22:25Z: 69 refusals, 69
"falling back to planner" lines, 1 L3 SCRIPT call, 0 new plans, over six
minutes, for a goal whose only action was an unknown kind. The log said the
agent was falling back. Nothing was.

An all-refused tick MUST do one of two things, and the implementation MUST
state which in the log:

1. **Yield the goal.** Unbind the script the first time a tick refuses every
   action it proposes, and clear the stale step list. Preferred, because the
   refusals are the signal that the script was wrong. This option needs no
   counter: an all-refused tick is not a thing to wait out, it is a script that
   cannot dispatch.
2. **Stop and report.** After N consecutive all-refused ticks, unbind the script
   and say why in chat and in the log. If this option is chosen, the counter
   MUST be consecutive -- a tick that dispatches something resets it -- so a
   script that intermittently succeeds is never torn down.

Silently rerunning a script that cannot dispatch is neither.

Option 1 is the shipped behaviour for this change. It is recorded here as a
permanent choice rather than a dated one, because option 2 leaves the bot idle
on a goal a planner could have taken. Option 2 remains the stated alternative
for a future implementation that has a reason to prefer stopping.

**Yielding alone does NOT return the goal to a planner.** Unbinding and
clearing `_plan_steps` removes the script as driver; it does not put the goal
back in front of `call_plan`. The goal is carried by
`plan_orchestrator.execute_task`, which runs once per goal on a worker thread
(`agent/agent.py:954`, `:1754`) and returns when that run ends. There is no
re-entry path: a cleared step list leaves the bot with no plan and no worker.
Trial 4.1's rerun on 2026-11-22 00:20-00:31Z confirmed this live -- after the
yield line the bot logged no `L3 PLAN` call and sat idle. A requirement that
yield alone re-plans the goal would be false; the obligation to re-plan is
stated separately in "A Yielded Goal Returns To The Planner".

Under option 1 there is no `N` and no counter, so the reset-consecutive property
does not apply: a script is unbound on its first all-refused tick whether or
not earlier ticks dispatched. An implementation that adopts option 2 MUST
define `N` as a single named constant rather than a literal at the comparison,
and MUST record the observation that chose it. The measured failure that
prompted this requirement ran 69 consecutive refusals, so any `N` below about 30
would have fired; a small value risks tearing down a script that was about to
dispatch.

#### Scenario: A script whose only action is refused stops being the driver

- **GIVEN** a bound script whose only action is an unknown kind
- **WHEN** a tick refuses every action it proposes
- **THEN** the script is unbound and the stale step list is cleared
- **AND** the reason is visible in the log
- **AND** the goal is NOT claimed to be handed back, because this step does not
  reach `call_plan`

#### Scenario: A tick that dispatches one action is not all-refused (option 1)

- **GIVEN** a bound script that proposes two actions, one refused and one
  dispatched
- **WHEN** that tick runs
- **THEN** the script stays bound, because the tick did not refuse every action

#### Scenario: Serialising to option 2 replaces the counter behaviour

- **GIVEN** an implementation that chose option 2 instead of option 1, and a
  script whose ticks have so far alternated refused and dispatched, so an
  all-refused run has started and been reset before
- **WHEN** fewer than `N` all-refused ticks occur in a row, and then a tick
  dispatches
- **THEN** the script stays bound, because that dispatch reset the count
- **AND** when a later run of `N` all-refused ticks happens with no dispatch
  between them, the script is unbound and the reason is in chat and in the log
- **NOTE** this scenario applies only to option 2; the shipped behaviour has no
  counter and unbinds on the first all-refused tick

### Requirement: A Yielded Goal Returns To The Planner

Yielding a goal off a script MUST NOT leave the bot with no driver. After an
all-refused tick unbinds the script, the goal MUST be put back in front of
`call_plan` so a plan is attempted again. Nothing in the current agent code
does this: `execute_task` has already returned by the time the script yields,
so the yield must re-submit the goal rather than rely on the next loop pass.

The re-submission MUST be bounded so a goal that cannot be planned does not
spin: if the re-planned attempt also yields, it MUST NOT re-submit
indefinitely, and the bound MUST be a single named constant with the reason
for its value recorded, not a literal.

#### Scenario: A yielded goal is planned again

- **GIVEN** a bound script that refuses every action it proposes
- **WHEN** the script yields the goal
- **THEN** a plan call is made for that goal
- **AND** the bot does not sit idle with the goal dropped

#### Scenario: A goal that yields repeatedly does not spin

- **GIVEN** a goal whose re-planned script also yields
- **WHEN** the re-submissions reach the stated bound
- **THEN** the agent stops re-submitting and says so in the log
- **AND** the bot does not re-plan the same goal forever

### Requirement: The Script Prompt Says Actions Take Effect After The Tick

An action a script dispatches is queued for the mod and takes effect after the
tick returns; the script cannot observe its outcome in the tick that requested
it. Trial 4.1's rerun at 2026-11-22 00:28Z showed the consequence: a script
logged "Sheared sheep ... 1/2" in the same tick it queued the action, before
anything had happened, so the log claimed a result the script could not yet
know. The prompt MUST state that a script's own report of an action is a
*request*, and that whether it succeeded is visible only on a later tick.

#### Scenario: The prompt states the one-tick delay

- **GIVEN** the rendered `SCRIPT_SURFACE` prompt
- **WHEN** a model reads what an action does
- **THEN** the prompt says the action takes effect after the tick returns
- **AND** the prompt does not imply the script can read the outcome in the same
  tick that dispatched it

### Requirement: The Dry Tick's Time Bound Is Its Own And Is Longer Than A Live Tick's

A dry tick runs ONCE, at bind time, and it is the first time a freshly written
script meets the runner. A live tick runs every two seconds against an already
warmed sandbox. Sharing one bound couples two different jobs to the slower
one's failure.

The two runs MUST use different bounds, and each MUST be a named constant:

- the **live tick** bound stays `SCRIPT_TIMEOUT = 0.3` s
  (`agent/script_client.py:109`), unchanged;
- the **dry tick** bound MUST be longer, `DRY_TICK_TIMEOUT = 2.0` s, and MUST
  be reached without widening the live bound.

Prod Mystic on image `aeab1dab` (2026-11-22 12:55-13:00Z) showed why: the first
ever prod runner call paid a cold-sandbox start, the dry tick exceeded 0.3 s,
and the agent logged `dry tick failed (runner fallback_timeout: read timeout
...)` on a 4824-character planner script that was otherwise good. A correct
script was refused for being the first to touch a cold sandbox.

The dry bound MUST NOT be reachable by a caller overriding the live bound, and
must not become a general "pass a bigger number" escape hatch: the live tick's
call path (`call_runner`) deliberately reads `SCRIPT_TIMEOUT` from the module
so it cannot be overridden, and that property MUST survive this change. The
dry bound is selected by the dry call itself, not by an argument any caller
can pass to the live path.

#### Scenario: A slow dry tick binds

- **GIVEN** a planner-authored script whose dry tick takes about 1 s to return
- **AND** the live tick bound is 0.3 s
- **THEN** the dry tick succeeds and the script is bound

#### Scenario: A slow live tick still falls back

- **GIVEN** a script already bound to the bot
- **WHEN** a live tick takes about 1 s to return
- **THEN** the live tick falls back to the planner as it does today
- **AND** the dry bound of 2 s does not extend the live tick's patience

### Requirement: A Script Reply Without A Task Echo Is Not A Rejected Plan

A reply that signals a script is not a step list, and the goal's text is
already known to the caller. Requiring the model to echo the goal back as a
`task` field, and rejecting the whole reply when it does not, fails a plan
whose action is otherwise complete.

When a plan reply signals a script (per `_signals_a_script`), a missing `task`
MUST be filled from the goal text rather than raised
(`agent/plan_schema.py:127` is where it is raised today). A reply that signals
NO script MUST keep the full contract, including `task`: the step-list path is
the ordinary case and its validation MUST NOT be weakened.

Prod Mystic, try 1 (2026-11-22 12:55-13:00Z) logged
`planning failed: plan missing required field: task` because the model omitted
the echo. The plan carried everything needed to run.

#### Scenario: A script reply with no task still plans

- **GIVEN** a plan reply that signals a script and omits `task`
- **AND** the goal text is "tell me when it gets dark"
- **WHEN** the reply is validated
- **THEN** the plan is accepted
- **AND** its `task` is the goal text

#### Scenario: A step-list reply with no task is still rejected

- **GIVEN** a plan reply that does NOT signal a script and omits `task`
- **WHEN** the reply is validated
- **THEN** it is rejected with "plan missing required field: task"

### Requirement: A Refused Script Bind With Nothing To Run Fails The Goal

When the planner hands back a script and the bind is refused, the orchestrator
falls back to the reply's step list so exactly one thing drives the goal. If
the reply has no steps, that fallback runs zero steps and marks the goal
complete: the player is told nothing and the goal looks successful
(`agent/plan_orchestrator.py:381-382`, then the phase-2 loop at `:398-403`).

A refused bind that leaves nothing to execute MUST end the goal **failed**,
with the refusal reason recorded, and MUST tell the player in a short chat line
that the script could not be started. It MUST NOT end `complete`, and MUST NOT
be silent.

Prod Mystic, try 2 (2026-11-22 12:55-13:00Z), after the bind was refused for the
dry-tick timeout: `goal not handed to its script; executing the step list`, zero
steps, then `plan finalized: complete`.

#### Scenario: A refused bind with no steps fails loudly

- **GIVEN** the planner's reply carries a script but no subtasks
- **AND** the bind is refused
- **WHEN** the orchestrator drives the goal
- **THEN** the goal is marked failed
- **AND** the refusal reason is recorded on the plan
- **AND** the player is sent a short chat line saying the script could not start

#### Scenario: A refused bind with steps still runs the steps

- **GIVEN** the planner's reply carries a script AND a non-empty step list
- **AND** the bind is refused
- **WHEN** the orchestrator drives the goal
- **THEN** the step list runs as it does today
- **AND** the goal's status is decided by those steps, not by the refusal

### Requirement: A Tick With A Snapshot MUST NOT Grow The Runner's Heap

The runner installs the game snapshot into the script sandbox on every tick
that carries one (`agent-script-runner src/engine.js`, `#installSnapshot`).
Installing it calls `ctx.getProp(handle, "snapshot")` and
`ctx.getProp(handle, "look")` and feeds each result to a `setProp` on the guest
global. Every `getProp` returns a QuickJS handle that holds an entry in the
**runtime-wide** HostRef table, and those entries live as long as the runtime
does — not as long as the context. Disposing only the outer `handle` therefore
leaks one HostRef entry per `getProp`, per tick.

Each tick that carries a snapshot MUST leave the runtime's retained memory
where it found it, within a bounded slack that does not grow with the number of
ticks. The bound MUST hold for a realistically large snapshot (40+ bots with
positions and inventories, a chat backlog), not only for a minimal one: the
leak is proportional to the installed payload, so a tiny fixture can make a
leaking runtime look flat for thousands of ticks.

The same rule applies to every `getProp`-into-`setProp` site, not only the
snapshot path. `#installApi` was fixed this way in `f63a623`; `#installSnapshot`
was not, and an unpatched runner died at 2,142 ticks on a 29-byte snapshot and
survives past 30,000 once its two inner refs are disposed.

#### Scenario: Steady ticks with a large snapshot keep the heap flat

- **GIVEN** a sandbox on a limited runtime with a warm-up of at least 20 ticks
- **WHEN** it is ticked 500 times, each tick carrying a snapshot of at least 100 KB
- **THEN** every tick succeeds
- **AND** retained memory after the run is not more than the starting reading
  plus a small fixed slack, and does not grow linearly with the tick count

#### Scenario: The bounding test fails on a leaking runner

- **GIVEN** the same large-snapshot test run against a runner that disposes only
  the outer handle in `#installSnapshot`
- **WHEN** the test completes
- **THEN** it fails, reporting growth per tick
- **AND** the reported growth is on the order of tens of kilobytes per tick, not
  a burst attributable to one-off warm-up allocations

#### Scenario: A snapshot-free tick is unaffected

- **GIVEN** a sandbox ticked with no snapshot argument
- **WHEN** the run completes
- **THEN** the heap is flat
- **AND** the snapshot-leak test does not depend on this path, because a
  snapshot-free tick never enters the leaking branch

#### Scenario: A failed install strands no refs

- **GIVEN** a runtime limited to a known heap
- **WHEN** a tick installs a snapshot whose `setProp` throws on a context that
  has already been disposed, and this happens repeatedly
- **THEN** the retained-memory growth stays flat across every attempt
- **AND** the growth does not scale with the number of failed installs

The install path MUST dispose the refs it created on both the success and the
failure path. `evaluate()` catches a throw from the install, so without this a
failed install is silent and its refs leak. That leak is a FIXED ~33.5 KB
(33496 bytes, measured against the real runtime on 2026-11-22) per failed
install, and it is independent of payload size: a 1825-byte and an 79807-byte
snapshot produced byte-identical deltas, because what is stranded is one HostRef
entry rather than a copy of the JSON. Two figures were stated here before and
both were wrong — an original "~480 KB, enough to exhaust a 32 MiB runtime in
about 66 of them" (R-2) and a "~209.5 KB at 40 bots, ~68 KB at one bot,
proportional to payload" (R-3), each withdrawn on 2026-11-22 after
re-measurement. The failure path is reachable in production, not only in tests — a
tick can tear down between install and bind, which is why `#installApi` gained a
`try/finally` on 2026-11-13.

#### Scenario: A throwing cleanup does not replace the install failure

- **GIVEN** a context that has already been disposed
- **WHEN** the install path runs its cleanup
- **THEN** the cleanup does not throw
- **AND** the error the caller sees is the original install failure

A bare `try/finally` is necessary but NOT sufficient here. On a disposed
context `dispose()` itself throws `Lifetime not alive` — measured — so a
`finally` that calls `dispose()` unguarded lets a SECOND throw, from the
cleanup, replace the `setProp` failure the caller was about to receive, and
skip the remaining disposes. An optional call (`dispose?.()`) does NOT avoid
this: the handle is non-null, so the call still runs and still throws. Each
dispose in the cleanup MUST be individually guarded.

The scope of that claim is deliberately narrow (R-1, 2026-11-22, corrected
after review). The guard does NOT rescue a failure the caller would otherwise
miss, and it does NOT change the recycle decision. Measured against the real
runtime: `setProp` on a disposed context throws
`QuickJSUseAfterFree("Lifetime not alive")`, which `evaluate()` classifies as
`wasm_trap` with `trap: true`, so `mustRecycle` is true with or without this
change, on both revisions. An earlier draft said the parent reported a
substituted `"context is gone"` message and flipped the recycle decision; that
was an artefact of a hand-written test fixture, not the runtime, and is
withdrawn. What the guard buys is exactly the two things above: the install
error stays the error the caller sees, and every later dispose still runs.

Guarding the dispose does NOT reclaim the handle, and a comment claiming it
does was measured false (2026-11-22): a handle whose context is already
disposed is NOT freed by that context's teardown -- `dispose()` throws
`Lifetime not alive`, the handle stays in the runtime-wide table, and
`rt.dispose()` later aborts with `list_empty(&rt->gc_obj_list)`. So the guard's
job is narrow: keep a cleanup error from replacing the install error. The
strand it leaves is permanent, and the only thing that avoids it is not
installing into a torn-down context at all.

#### Scenario: A throw mid-install still disposes everything the install built

- **GIVEN** an install path that creates one container object and then binds
  several handles into it, each in its own guarded `try/finally`
- **WHEN** a bind throws partway through, so the method does not reach the
  container's own dispose
- **THEN** the container is disposed anyway
- **AND** the handles bound before the throw are disposed
- **AND** the error the caller sees is the original bind failure

A per-dispose guard is NOT sufficient for this case, because nothing in the
handles' cleanup throws — the throw simply leaves the loop, so the code after
it never runs. Measured on `#installApi` (2026-11-22): a first-bind failure
disposed its one loop handle and left the api object in the runtime-wide table,
at the ~34.8 KB/occurrence recorded for that table above. The container's
dispose MUST be owned by a scope that encloses the whole install — one outer
`try/finally` — rather than by a statement reached on the success path. Every
handle is disposed exactly once on every path: an inner `finally` owns each
loop handle, the outer `finally` owns the container.

### Requirement: A Script Can Look Up What The Tick Already Saw

A script MUST be able to ask questions of the data the agent already sent for
that tick, through a `look` object installed beside `api`, and a lookup MUST
NOT spend a host call, reach the network, or reach the mod.

#### Scenario: A lookup answers from the snapshot
- **GIVEN** a tick whose snapshot carries `nearby.mobs` including a sheep
- **WHEN** the script calls `look.entities('sheep')`
- **THEN** it returns `{ ok: true, kind: 'entities', matches: [...] }` with each
  sheep's `distance`
- **AND** `hostCalls` for the tick is unchanged by the call

#### Scenario: A lookup beyond the snapshot points at the query function
- **GIVEN** a snapshot whose `nearby.blocks` covers radius 5
- **WHEN** the script asks for a block within 40 blocks
- **THEN** the lookup MUST NOT return an empty list that reads as "nothing there"
- **AND** it MUST report that the search did not extend that far, and name the
  beyond-snapshot search (its exact name is settled by the lead once
  `tasks.md` §7's option is chosen; do not hard-code `query.blocks` in code until
  then)
- **AND** the snapshot lookup itself MUST still spend no host call

#### Scenario: A lookup reports the age of what it searched
- **GIVEN** a tick whose snapshot was refreshed up to 2000 ms before the tick
- **WHEN** the script asks the snapshot's age
- **THEN** the lookup MUST report that age in milliseconds
- **AND** the age MUST be derived from the envelope's `server_ms` with no extra
  host call

#### Scenario: A block's display name is not its kind
- **GIVEN** a snapshot whose `nearby.blocks` entry carries a display name such
  as "Oak Planks" and no registry id
- **WHEN** the script tries to match a block by its registry id or its state
  (for example a flower's colour)
- **THEN** the lookup MUST NOT claim to have answered it
- **AND** the documented answer MUST be that neither the display name nor a
  registry id carries block state, so the lookup is not attempted

#### Scenario: The nearest K are the nearest, not the first met
- **GIVEN** a bot at the origin, a chest at (2,0,2) and another at (-5,-5,-5),
  and K=1 for that block id
- **WHEN** the cache is refreshed
- **THEN** the kept entry MUST be (2,0,2), squared distance 8, and not
  (-5,-5,-5), squared distance 75
- **AND** an implementation that keeps whichever candidate the x,y,z scan met
  first MUST fail this scenario
- **AND** equal squared distances MUST be broken by scan order, stated in the
  requirement, so the same world always gives the same payload

#### Scenario: A lookup cannot act
- **GIVEN** the `look` object built for a tick
- **WHEN** its construction is inspected
- **THEN** it MUST hold no reference to `api`
- **AND** no lookup path MUST reach `accept()`, the function that spends the
  host-call budget
- **AND** the `query` functions added beside it MUST be the same: they spend a
  host call but can only read, and none of them dispatches a directive

#### Scenario: A lookup result is a copy
- **GIVEN** a lookup that returned a list
- **WHEN** the script mutates that list
- **THEN** a second lookup in the same tick MUST be unaffected

#### Scenario: A dry tick sees the same lookups
- **GIVEN** one snapshot and one script
- **WHEN** the script is dry-ticked and then live-ticked
- **THEN** every lookup MUST return the same value in both

#### Scenario: A namespaced kind matches a bare one
- **GIVEN** a snapshot whose `nearby.blocks` entry carries `id`
  `minecraft:iron_ore`, the form the game's own producer emits
- **WHEN** the script calls `look.blocks('iron_ore')` with the bare name
- **THEN** it MUST match that entry
- **AND** the answer MUST be the same one `look.blocks('minecraft:iron_ore')`
  gives for the same snapshot

#### Scenario: An unnamespaced entry matches a namespaced needle
- **GIVEN** a snapshot whose `nearby.blocks` entry carries a bare `id`
  `iron_ore`, a form the game does not emit today
- **WHEN** the script calls `look.blocks('minecraft:iron_ore')`
- **THEN** it MUST still match that entry
- **AND** the two forms MUST compare equal in both directions, so a script
  never has to know which form the game sends

#### Scenario: An ore kind also matches its deepslate variant
- **GIVEN** a snapshot whose `nearby.blocks` carries `id`
  `minecraft:deepslate_diamond_ore`, as trial 4.2 did (2026-11-22 05:02Z)
- **WHEN** the script calls `look.blocks('diamond_ore')`
- **THEN** it MUST match that entry, so a caller that asks for an ore is
  not silently told there is none
- **AND** the bare form MUST behave identically, so `look.blocks('minecraft:diamond_ore')`
  and `look.blocks('diamond ore')` give the same answer
- **AND** the reverse MUST hold: a `diamond_ore` entry MUST match a
  `deepslate_diamond_ore` needle, because the caller cannot know which
  variant the world happens to contain

#### Scenario: The deepslate variant is a fallback, not a replacement
- **GIVEN** a snapshot carrying BOTH `minecraft:diamond_ore` and
  `minecraft:deepslate_diamond_ore`
- **WHEN** the script calls `look.blocks('diamond_ore')`
- **THEN** BOTH MUST be returned, because the caller asked for the ore and
  the deeper variant is the same ore
- **AND** a kind with no deepslate counterpart MUST match exactly one
  entry, so the rule never widens a non-ore lookup

#### Scenario: Only ores get the variant rule
- **GIVEN** a snapshot whose `nearby.blocks` carries `id` `minecraft:deepslate`
  and another carrying `minecraft:cobbled_deepslate`
- **WHEN** the script calls `look.blocks('stone')`, `look.blocks('deepslate')`
- **THEN** the variant rule MUST NOT apply, because neither is an `_ore`,
  and the exact-match scenarios above MUST still hold

#### Scenario: Only a leading namespace is stripped
- **GIVEN** a snapshot whose `nearby.blocks` carries `id` `a:minecraft:b`
- **WHEN** the script calls `look.blocks('minecraft:b')`
- **THEN** it MUST NOT match, because only one leading `minecraft:` prefix is
  removed from each side and nothing else is rewritten
- **AND** matching MUST remain exact after that one strip, so
  `look.blocks('iron')` MUST NOT match `minecraft:iron_ore`

### Requirement: A Script Declares The Searches It Needs And Reads Them As `look.queries.<name>`

A script MUST be able to search the world the way the planner's own
`find_blocks` / `find_entities` / `locate` do (owner A2, 2026-11-25 00:59Z), and
the lead settled HOW on 2026-11-25 04:17Z: **option 1 with a declared list.**

A script declares the searches it wants in a top-of-script statement named
`queries` (`const queries = [...]` or `queries = [...]`), using the same kinds
and parameters as the bot's existing query functions (`agent/api.py`). Before
each tick, the agent runs exactly those declared queries through the existing
mod reads and installs each result on the `look` object's `queries` map under
the declared `name`. Script code reads `look.queries.<name>` like any other
lookup: a plain value, no call, no host call. It is NOT `look.<name>` because
`look` already has accessors named `blocks`, `entities`, `age`, `inventory`,
`self` and `task`; a declaration named `blocks` would either overwrite one of
them or silently lose to it, depending on the order of an edit nobody would
notice. One reserved namespace has neither failure.

```js
queries = [
  {name: "ore",   kind: "blocks",   id: "minecraft:diamond_ore", radius: 32},
  {name: "cows",  kind: "entities", id: "minecraft:cow"},
  {name: "here",  kind: "block_at", x: 10, y: 64, z: 10},
]
var first = look.queries.ore.matches[0]
return first
  ? api.do("goto", {x: first.position.x, y: first.position.y, z: first.position.z})
  : api.done("none");
```

A `blocks` match carries `block` (registry id), `name` (display name) and
`position` (`{x, y, z}`) — the fields `BotPlayer.findBlocks` builds — and the
action that walks there is the existing `goto` kind taking `x`/`y`/`z`, not a
`goto_block` kind (there is none; an example that says otherwise is refused at
dispatch, found on the 2026-11-27 live probe).

The properties that make this the chosen design MUST hold:

- **Zero host calls.** A declared query is answered from data the agent fetched
  BEFORE the tick, so reading `look.queries.<name>` spends none of the 8 host calls and
  the sandbox stays hermetic (`src/engine.js` `#installSnapshot`). `look` keeps
  closing over the snapshot; the query results are additional read-only data on
  it, not a host function.
- **No stall.** The mod reads happen on the agent's tick boundary, before the
  script is evaluated, never inside it, so a slow `findBlocks` delays that tick's
  start (a bounded, visible cost) rather than blocking mid-script with no
  timeout.
- **No state across ticks.** The results live for exactly the tick they were
  fetched for, like the snapshot itself (§4.4: nothing a script declares survives).
- **A tick with no declared queries costs zero mod reads.** No `queries`
  assignment, or an empty list, MUST fetch nothing.

**How `queries` is read.** The script is JavaScript and runs as a function body
(`src/engine.js:evaluate`, contract §4.4); nothing it declares at top level
survives, and the sandbox has no JS parser exposed to the agent. The agent
therefore MUST read the declaration from the SOURCE TEXT before evaluating,
without executing any script code, by a strict parse that accepts only a literal
form: a declaration `[const|let|var] queries = <literal>` whose right side is an
array of object literals with only the allowed keys (`name`, `kind`, `id`,
`x`/`y`/`z`, `radius`, `max`). Anything dynamic (a function call, a property access, a spread, a
template literal, a variable reference) MUST be refused at bind time with a clear
reason, NOT silently ignored and NOT executed — a declaration that is executed to
be read is arbitrary code running before the tick's budget.

Two rules the parse MUST also enforce, because dropping them was measured to
pass attackers (prototype in tasks 7.1): **the declaration MUST appear at most
once** (a second `queries =` later in the script would diverge from the one that
was validated), and **nothing MAY follow the closing `]` on its statement except a
terminator or comment** (`queries = [...literal...] + evil()` otherwise parses as
the array while `+ evil()` still executes when the script runs — validation that
gives false assurance). A `__proto__` or other unknown key is refused by the key
allow-list, not by trusting the JSON parse.

The terminator rule is about the STATEMENT ENDING, not about the character that
ends it: a `;` starts a NEW statement, so `queries = [...]; evil()` is refused on
the same grounds as `+ evil()` — accepted by a literal reading of "on its
statement", which is why the intent is written out here (review finding F-1,
measured: the first implementation accepted exactly that form, and the runner
service executes the script). Concretely: after the closing `]`, on the
terminator's line, only spaces, tabs, `\r`, one or more `;` and comments may
appear; anything else is refused. The first line break ends the statement and
code may follow it. The `;` is optional — `] // why` then code on the next
line is as legal as `]; // why` then code (F-2, then the residual the re-check
found: pinning only the `];` shapes let the no-semicolon forms be refused while
this sentence claimed they were allowed). A comment MUST NOT span more than one
line: `]; /* a` / ` */ evil()` is refused, not treated as a line break —
measured, allowing it accepted a form where `evil()` runs.

**The declaration is validated when a script is BOUND, before it has run a tick.**
The same parser runs at `tick()` time to read the queries; a script whose
declaration is invalid at bind time MUST be refused there with a reason naming
the declaration (the path a hand-written binding already takes, `PlannerScriptBindTest`),
so a broken declaration is visible in the bind log rather than only in a tick's
detail line. A tick whose declaration becomes invalid mid-run (a script edited
under a live binding) is refused at the tick, never executed with a partial list.

**Kinds and parameters** (from `agent/api.py`, which wraps the mod):

| kind | declared keys | mod call | caller-side clamp |
|---|---|---|---|
| `blocks` | `id`, `radius`, `max` | `api.find_blocks(bot, id, radius, max)` (`agent/api.py` `find_blocks`) | radius <= 32, max <= 16 |
| `entities` | `id`, `radius` | `api.find_entities(bot, id, radius)` (`agent/api.py` `find_entities`) | radius <= 32 |
| `block_at` | `x`, `y`, `z` | `api.block_at(bot, x, y, z)` (`agent/api.py` `block_at`) | one cell |
| `locate` | `id` | `api.locate(bot, id)` (`agent/api.py` `locate`) | fixed chunk_radius 100 |

The clamps above are a PROPOSAL; the numbers that decide their safety are
measured by tasks 7.6 (scan cost) and the lead accepts or overrules them. A
declared value above a clamp MUST be narrowed to it and the clamp MUST be
reported in that query's result, so the script can tell a search was narrower
than it asked.

**A failed or timed-out query is not an empty result.** Each result MUST be
`{ ok: false, reason, message }` on failure or timeout, never `{ ok: true,
matches: [] }`, for the reason `look` already draws (`src/look.js:103-110`):
"searched, found none" and "could not search" are different facts. One failed
query MUST NOT fail the tick or drop the other queries — each is independent and
each failure is reported in its own `look.queries.<name>`.

**What a successful result looks like.** The mod answers `find_blocks` as
`{blocks: [...]}` and `find_entities` as `{entities: [...]}`
(`HttpApiServer.java`, `find_blocks` / `find_entities` cases), and the runner
binds the agent's `queries` map verbatim. So the agent MUST rename those lists
to `matches` before installing them: the examples above read
`look.queries.ore.matches`, and a script written exactly as this spec shows MUST
work. A `blocks` or `entities` result is `{ ok: true, kind, matches: [...] }`.
`block_at` and `locate` are single answers, not lists: their result keeps the
mod's own fields (`block_at`: the block map; `locate`: its `found`/position
fields) and adds `ok` and `kind`. A unit test that stubs `find_blocks` to return
`matches` directly does NOT satisfy this requirement — it hides the real
response shape the agent has to normalise.

**A duplicate name is refused.** Two declarations with the same `name` would
silently make one overwrite the other, so it MUST be refused at bind time with a
reason naming the name. Duplicates of the same `(kind, id)` under DIFFERENT names
are allowed and collapse to one mod call, because they are one search.

**Read-only.** The query path MUST NOT reach any mod route that moves, mines,
places, attacks or sets a directive. It calls only the four reads above.

The mod clamps nothing: `HttpApiServer.java:1117-1134` takes whatever `radius` and
`max` it is sent, and `findBlocks` iterates the full cube
(`BotPlayer.java:1286-1309`). So the clamp lives in the agent, before the call.

#### Scenario: A declared query answers from data fetched before the tick
- **GIVEN** a script declaring `queries = [{name:"ore", kind:"blocks", id:"minecraft:diamond_ore", radius:32}]`
- **WHEN** the tick runs
- **THEN** `look.queries.ore` MUST be the result of one `find_blocks` call made BEFORE
  the script was evaluated
- **AND** reading `look.queries.ore` MUST spend no host call
- **AND** with the real `find_blocks` answer `{blocks: [...]}`, the script MUST
  read `{ok: true, kind: "blocks", matches: [...]}` (the agent renamed the list)

#### Scenario: A script reads matches exactly as this spec's example does
- **GIVEN** a declared `blocks` query and a real `find_blocks` answer carrying two blocks
- **WHEN** the tick installs the result
- **THEN** `look.queries.<name>.matches` MUST be those two blocks, `ok` MUST be true
- **AND** `look.queries.<name>.blocks` MUST be absent
- **AND** the test MUST feed the api's real response shape, not a hand-made `matches`
  (the 2026-11-27 live probe read `matches` from the spec example and got undefined
  while `ok` was true, because the agent passed `{blocks: [...]}` through)

#### Scenario: A tick with no declared queries costs no mod read
- **GIVEN** a script with no `queries` assignment
- **WHEN** the tick runs
- **THEN** no `find_blocks`, `find_entities`, `block_at` or `locate` call MUST be made
- **AND** `look` MUST still answer from the snapshot as before

#### Scenario: A dynamic declaration is refused, not executed
- **GIVEN** `queries = [getQuery()]` or `queries = someVar`
- **WHEN** the script is bound
- **THEN** it MUST be refused with a reason naming the declaration, before any
  part of it runs
- **AND** no code inside the declaration MUST execute

#### Scenario: A declared value above the clamp is narrowed and says so
- **GIVEN** `{kind:"blocks", id:"minecraft:stone", radius:128}`
- **WHEN** the query is run
- **THEN** the mod MUST be asked for at most radius 32
- **AND** `look.queries.<name>` MUST carry the clamp (e.g. `clamped: {radius: 32}`)

#### Scenario: A failed query is not an empty one
- **GIVEN** a declared query whose mod call times out
- **WHEN** the tick runs
- **THEN** `look.queries.<name>` MUST be `{ ok: false, reason: "timeout", ... }`
- **AND** it MUST NOT be `{ ok: true, matches: [] }`
- **AND** the other declared queries MUST still be present and correct
- **AND** the tick MUST NOT fail because of it

#### Scenario: A query cannot act
- **GIVEN** the code that runs declared queries
- **WHEN** its call sites are inspected
- **THEN** they MUST be only `find_blocks`, `find_entities`, `block_at`, `locate`
- **AND** no `goto`, `mine`, `place`, `attack` or `set_directive` route

**An answer carrying an `error` key is a failure, not an empty list.**
Both search verbs catch their own exception and complete with an empty list
(`HttpApiServer` `find_blocks` at `:1124`, `find_entities` at `:1134`), so today
a search that threw and a search that found nothing are the same bytes on the
wire. The mod MUST answer a failed search from either verb with an `error` key
beside its list (`{blocks: [], error: "<reason>"}` and
`{entities: [], error: "<reason>"}`, the shape `scan_data` already uses at
`:1420`), and this agent MUST read that key as a failure for that query only:
`look.queries.<name>` is
`{ok: false, reason: "error", message: <the mod's own text>}`. A bare
`{blocks: []}` or `{entities: []}` with no `error` key MUST stay
`{ok: true, matches: []}`, because that is a search that ran and found nothing --
the opposite fact, and the one a planner acts on. Both halves are required: the
mod fix alone leaves the agent reporting success on a failed search, and the
agent guard alone is inert while nothing sends an error key. The agent half is
one rule for both verbs, because `_normalise_query_result` reads the `error` key
without knowing which verb produced it; a second, parallel agent rule for
`entities` would be a copy that can drift.

#### Scenario: A search that threw is a failure, not an empty result
- **GIVEN** a declared `blocks` query, and the mod answering
  `{blocks: [], error: "findBlocks error: ..."}` because its search threw
- **AND** a declared `entities` query, and the mod answering
  `{entities: [], error: "findEntities error: ..."}` because its search threw
- **WHEN** the tick runs
- **THEN** each `look.queries.<name>` MUST be `{ ok: false, reason: "error" }`
- **AND** each `message` MUST carry the mod's own error text, so the planner can
  tell a broken search from a world with nothing in it
- **AND** the other declared queries MUST still be present and correct
- **AND** the tick MUST NOT fail because of either one

#### Scenario: A genuine empty result stays a success
- **GIVEN** a declared `blocks` query, and the mod answering `{blocks: []}` with
  no `error` key because the search ran and found nothing
- **AND** a declared `entities` query, and the mod answering `{entities: []}`
  with no `error` key for the same reason
- **WHEN** the tick runs
- **THEN** each `look.queries.<name>` MUST be `{ ok: true, matches: [] }`
- **AND** neither MUST carry `ok: false`, so the fix never turns a world with
  nothing in it into a reported failure

#### Scenario: The error-key path is driven by the mod's answer, not a raising stub
- **GIVEN** the tests for the scenarios above
- **WHEN** they are inspected
- **THEN** they MUST feed `{blocks: [], error: ...}` and
  `{entities: [], error: ...}` through the agent's declared-query normaliser
- **AND** they MUST NOT stand in for it by making `find_blocks` or
  `find_entities` raise, because a raising stub exercises the transport's
  `except` branch rather than the error-key path, and the guard could be deleted
  with the suite still green

### Requirement: A Script Can Read Its Own Inventory Through The Lookup

A script MUST be able to ask what the bot is carrying through
`look.inventory()`, a **read-only** lookup beside `look.blocks`,
`look.entities` and `look.age`. It MUST return the items in the snapshot's
`state.inventory` as a deep copy, MUST NOT spend a host call, MUST NOT let the
script mutate the snapshot by mutating what it receives, and MUST NOT offer any
way to change the inventory — a script that wants to move items calls the
existing `do` directives. The inventory the answer describes is the one the
tick's snapshot carries, so it is as old as the snapshot and is reported
alongside `look.age()`.

This exists because a script could otherwise not tell whether it held the tool
its work needs. The 2026-11-21 trial had a script written to shear sheep idle
with no shears in inventory, and `look` offered no way to check.

#### Scenario: The inventory is readable with no host call
- **GIVEN** a snapshot whose `state.inventory` carries 1 `minecraft:shears` and
  12 `minecraft:iron_ore`
- **WHEN** the script calls `look.inventory()`
- **THEN** it returns `{ ok: true, items: [...] }` naming both stacks
- **AND** `hostCalls` for the tick is unchanged by the call

The host-call half is measured, not asserted in prose: the binding reports
`host_calls` per tick, and `look-engine.test.mjs` evaluates 200 calls to every
`look` accessor — `inventory()` included — on a real sandbox and requires the
count to stay at 0. Wiring any accessor through `accept` reds it.

#### Scenario: A script cannot change the snapshot through it
- **GIVEN** a `look.inventory()` result
- **WHEN** the script mutates the returned list or any item in it
- **THEN** a second `look.inventory()` in the same tick MUST return the
  unmodified inventory
- **AND** the tick's own snapshot MUST be unchanged

#### Scenario: The inventory is read-only
- **GIVEN** the `look` object built for a tick
- **WHEN** its properties are enumerated
- **THEN** every one of them MUST be read-only, and `look.inventory` MUST be a
  function returning data rather than anything that accepts a change

#### Scenario: An empty inventory says so rather than failing
- **GIVEN** a snapshot whose `state.inventory` is empty
- **WHEN** the script calls `look.inventory()`
- **THEN** it MUST return `{ ok: true, items: [] }`
- **AND** it MUST NOT throw, so a script can test for a missing tool without a
  guard

### Requirement: The Script Prompt Names The Fields Of Every Lookup Entry

`SCRIPT_SURFACE` MUST state the fields of every entry a lookup can return, not
only the fields of `look.blocks` entries. A script author reads that constant
and nothing else; a field it does not name is a field the author must guess,
and a wrong guess reads as an absent value rather than an error.

The three lookups return entries with **different identity fields**, and the
prompt MUST name each:

- a block entry carries `{id, block, position}`, where `id` is the namespaced
  registry id;
- a mob entry carries `{type, name, position, distance}`, where the identity
  field is `type`, not `id`;
- an inventory item carries `{slot, item, count, display_name, ...}`, where the
  identity field is `item`, not `id`.

`look.inventory()` returns the producer's stack objects verbatim; it does not
normalise them and MUST NOT be changed to do so, because a read-only accessor
that rewrote the shape would misreport what the bot carries. Naming the fields
in the prompt is what keeps that faithful copy usable.

#### Scenario: A script author is not left to guess an item's identity field

- **GIVEN** the rendered script prompt built from `SCRIPT_SURFACE`
- **WHEN** the prompt describes `look.inventory()`
- **THEN** it MUST name `item` as the field carrying the item id, because that
  is the field the producer actually sends and the one a script must read

#### Scenario: An author can tell the three entry shapes apart

- **GIVEN** the rendered script prompt
- **THEN** it MUST state that a block uses `id`, a mob uses `type`, and an
  inventory item uses `item`, so a script that reads `items[0].id` is a
  mistake the prompt could have prevented

### Requirement: A Script's Result Reaches The Planner On Stated Triggers Only

A script's result MUST be the value passed to `api.result(v)` — NOT its
top-level return value, which ends the tick and reaches no result field
(lead rule, 2026-11-10; `worker.js:147`, `32b592a`). The stored result MUST be
delivered to the planner when the script reports completion, when it errors,
or when it states an escalation — and on no other tick. Delivery MUST NOT
depend on a player message arriving: a finished script's result MUST start a
planner call of its own, with NO rate cap and NO cooldown (owner A2,
2026-11-25 00:59Z). The only bound is serialisation: at most ONE
result-triggered planner call in flight per bot at a time, whichever script
produced it.

`api.result(v)` MUST cost one of the tick's 8 host calls. Its value MUST be
JSON-serialised and capped by the same 2 KiB marked cut as any other result.
When a script calls `api.result` more than once in a tick, the LAST value MUST
be the one kept. A call to `api.result` MUST NOT itself raise a delivery
trigger: it stores a value, and the trigger remains done/error/escalate.

#### Scenario: A completed goal delivers one result
- **GIVEN** a script that calls `api.result({ done: true, ... })`
- **WHEN** it is ticked repeatedly
- **THEN** exactly one result MUST be delivered
- **AND** the binding MUST be released

### Requirement: A Result Carries Its Goal, And `done` Closes It

A delivered result MUST carry the id of the goal whose script produced it.
`_script_hold` is not that goal: the bind RELEASES the hold (2a.6), so by the
time a script reports, the hold is already None and cannot name its owner. The
surviving record is the active goal id, and the result MUST be stored with it
rather than with an empty string.

A result whose trigger is `done` MUST close its goal. It MUST NOT be handed to
the orchestrator as a new task, and the planner MUST NOT be asked to decompose
it: doing so produced a plan for the text "Script result (done): ..." and the
L3 planner declined with a clarify question, asking the player whether there
was a new task (observed on test 03:22Z). The player asked for one thing and
got a question back.

Reporting the outcome to the player is part of closing, not a separate plan.
Triggers other than `done` keep the existing delivery path.

#### Scenario: A done result carries the goal it was bound for
- **GIVEN** a script bound while running goal `chat:dashboard:hello#1`
- **WHEN** the script reports `done`
- **THEN** the stored result's goal id MUST be `chat:dashboard:hello#1`
- **AND** it MUST NOT be the empty string

#### Scenario: A done result closes its goal instead of planning again
- **GIVEN** a pending `done` result for the bot's current goal
- **WHEN** the result-delivery point runs
- **THEN** the goal MUST be closed and its outcome reported to the player
- **AND** no new orchestrator run MUST start from the result text
- **AND** the planner MUST NOT be asked whether there is a new task

#### Scenario: A result for a goal that is no longer current is still dropped
- **GIVEN** a pending result stored for goal A
- **WHEN** the bot's active goal is now B
- **THEN** the result MUST be discarded rather than closing or re-planning B

### Requirement: A Result Whose Script Said It Failed Must Not Close The Goal As Done

A result whose text reports failure MUST NOT close its goal as though the work
succeeded. A goal closed as `done` is terminal: the script binding is released
and nothing re-plans it, so closing on a failure strand the player's request
with a green chat line and no further attempt.

WHAT "REPORTS FAILURE" MEANS: the script's own boolean `done` field, not its
prose. A script reports success or failure by passing an object to
`api.result({done: true, ...})` / `api.result({done: false, reason: ...})`; the
tick carries that flag to the result slot as `ok`, and it alone selects the
trigger. Text-matching was the alternative and is unusable: a successful result
may legitimately contain the word "failed" ("first attempt failed, retried"),
and a failed one need not use it. A result that carries no verdict -- a plain
string, a non-object JSON value, a non-boolean `done`, or text cut mid-JSON by
the size cap -- MUST keep the `done` trigger it had before this requirement, so
every script written against the older contract keeps working.

DECISION: a failure result MUST hand the goal back to the planner rather than
closing as done-with-failure. The reasoning is that the two outcomes are not
symmetrical. A `done` result is the end of the work: re-planning it makes the
planner decompose text it already finished (the 03:22Z clarify question). A
failure is the *absence* of the outcome the player asked for, and the planner is
the only component that can choose a different approach -- retry the same target
from elsewhere, pick another ore, or tell the player it cannot be done. Closing
it as done silently converts "could not" into "did", which is the one reading
no script is entitled to make on the player's behalf.

The owner removed the hourly cap and the cooldown (A2, 2026-11-25 00:59Z): a
script may wake the planner on every stated trigger, and the scripts are written
by a local model, so the planner call is the thing worth doing, not the thing to
throttle. What still holds a failure is serialisation, not a rate: a failure
result MUST consume the same ONE in-flight planner slot as any other
result-triggered call, and a result that arrives while a call is in flight MUST
stay pending rather than be dropped. No failure result closes the goal as done
and none is discarded.

#### Scenario: A failure result re-plans instead of closing
- **GIVEN** a pending result whose script reported `{done: false}`
- **WHEN** the result-delivery point runs and no planner call is in flight
- **THEN** the planner MUST be asked what to do next
- **AND** the goal MUST NOT be closed as done
- **AND** the player MUST NOT be told the work succeeded

#### Scenario: A second failure while one is in flight waits, and is not dropped
- **GIVEN** a `{done: false}` result already handed to the planner, and that
  call still in flight
- **WHEN** another `{done: false}` result becomes pending
- **THEN** no second planner call MUST start while the first is in flight
- **AND** the second result MUST stay pending rather than be discarded
- **AND** the goal MUST be left open rather than closed as done

#### Scenario: A successful result still closes
- **GIVEN** a pending result whose script reported `{done: true}`
- **WHEN** the result-delivery point runs
- **THEN** the goal MUST be closed and its outcome reported, as before

### Requirement: A Failed Tick's Result Must Not Be Silently Dropped

A tick the runner reports as `error` MUST NOT discard a result the script
stored in that same tick. The runner already carries it (`src/main.js` sets
`result` on both the ok and error responses, for a script that calls
`api.result` and then throws), but the agent treats every non-`ok` status as a
fallback and returns before holding the result -- so the one case the runner
went out of its way to preserve is the one the agent throws away.

A failed tick MUST still fall back to the planner, as it does today: the
script's actions for that tick are not trusted. Only the *result* MUST survive,
delivered with the failure classification above so it cannot close the goal as
done.

#### Scenario: A script that reports and then throws keeps its result
- **GIVEN** a script whose tick calls `api.result` and then throws
- **WHEN** the runner answers `status: error` with that result
- **THEN** the result MUST be held rather than dropped
- **AND** it MUST be treated as a failure result, not a done one
- **AND** the tick MUST still fall back to the planner

#### Scenario: The return value is not the result
- **GIVEN** a script whose top-level `return` carries a value and which never
  calls `api.result`
- **WHEN** its tick completes
- **THEN** no result MUST be delivered from the return value
- **AND** the tick MUST still end as the return-value rule says it does

#### Scenario: The last result call in a tick wins
- **GIVEN** a script that calls `api.result` twice in one tick with different
  values
- **WHEN** the result is delivered
- **THEN** the delivered value MUST be the second call's
- **AND** the first value MUST NOT appear

#### Scenario: Reporting costs a host call
- **GIVEN** a script that uses all 8 host calls, one of them `api.result`
- **WHEN** the tick runs
- **THEN** `api.result` MUST be counted among the 8 and MUST NOT be free

#### Scenario: Reporting does not trigger delivery by itself
- **GIVEN** a script that calls `api.result` and then keeps ticking, never
  reaching done, error or escalation
- **WHEN** several ticks pass
- **THEN** no planner call MUST be triggered by the `api.result` call

#### Scenario: An error delivers a result rather than only a log line
- **GIVEN** a script whose tick fails
- **WHEN** the agent processes the failure
- **THEN** a result MUST be delivered to the planner

#### Scenario: One result-triggered call in flight per bot
- **GIVEN** a bot whose result-triggered planner call is in flight
- **WHEN** another script result becomes pending for that bot, from any script
- **THEN** no second result-triggered planner call MUST start until the first
  returns
- **AND** the pending result MUST stay in the slot, not be dropped
- **AND** when the in-flight call returns, the pending result MUST be delivered
  on the next pass — there is no wait to serve beyond the in-flight call, no
  15-minute cooldown and no hourly budget

#### Scenario: Serialisation is per bot, not per script and not global
- **GIVEN** two bots, each with a script result pending at the same moment
- **WHEN** both are delivered
- **THEN** each bot MUST get its own planner call, because neither bot's
  in-flight call is the other's
- **AND** one bot's in-flight call MUST NOT hold back the other's result

#### Scenario: A result has a size cap
- **GIVEN** a script calling `api.result` with more than 2 KiB of JSON
- **WHEN** the result is delivered
- **THEN** it MUST be truncated with a marker
- **AND** it MUST NOT be dropped

#### Scenario: The planner reads a result without an extra call
- **GIVEN** a delivered result
- **WHEN** the planner next runs
- **THEN** the result MUST appear in that call's prompt
- **AND** no additional planner call MUST be made to carry it

#### Scenario: A result is only read by the goal that produced it (DEFERRED)
**Deferred (task 3.9):** the rule below is implemented and tested on the slot,
but it cannot fire in production yet, because a tick carries no goal id out of
the sandbox -- a held script returns SCRIPT_HELD before it ticks, so every
stored result is keyed to goal `""`. Nothing this change ships depends on the
discard; it starts working unchanged once a tick reports the goal it ran for.
- **GIVEN** a result keyed to bot and goal id
- **WHEN** the planner next runs for a different goal id
- **THEN** the result MUST NOT be rendered into that call's prompt
- **AND** it MUST be discarded with both goal ids logged

#### Scenario: A finished script's result reaches the planner with no player
- **GIVEN** a script that reaches `done` and releases its binding
- **WHEN** no player message arrives afterwards
- **THEN** the result MUST reach `call_plan` for its own goal without waiting
  for a player
- **AND** that call MUST be started by the result-triggered entry point, not by
  `_maybe_plan`

#### Scenario: A result arriving mid-call is queued, not injected
- **GIVEN** a planner call in flight for a goal
- **WHEN** a result for that goal arrives
- **THEN** the in-flight call MUST NOT be interrupted or given the result
- **AND** the result MUST be delivered on a later pass, once the in-flight call
  has returned

#### Scenario: A stale result is discarded, not delivered (DEFERRED)
**Deferred (task 3.9):** not shipped by this change. No age rule is
implemented, and the requirement below is the target for the step that gives a
tick its goal id, not a promise about this ship.
- **GIVEN** a pending result older than 30 minutes
- **WHEN** a planning call for its goal next runs
- **THEN** the result MUST NOT be rendered
- **AND** the discard MUST be logged

#### Scenario: A result never enters a field the trainer reads
- **GIVEN** a delivered result rendered into a `call_plan` prompt
- **WHEN** the reply is recorded for the DPO trainer
- **THEN** the result MUST NOT appear in `response_raw`, `parsed`, or any other
  field the trainer reads
- **AND** the prompt path that renders it MUST be the only surface it touches

#### Scenario: Logs and actions are not results
- **GIVEN** a script that calls `api.log` and `api.do` and returns nothing
- **WHEN** the tick completes
- **THEN** no result MUST be delivered

### Requirement: The Planner Prompt Documents The Whole Script Surface

A feature the planner cannot see is a feature no planner-written script can
use. The planner prompt's script section (the text the LLM is given when it may
answer with a program instead of steps) MUST document every call a script can
make, in the shape the runner actually binds: the seven `api.*` host calls, the
`look` global, and `api.result(v)`. It MUST state each one's signature, what it
returns, and when to reach for it. It MUST NOT describe a call that the runner
does not bind, because a prompt that offers one teaches the model to write
scripts that throw.

The section is paid for on every planner call, so it MUST stay short: a line
or two per call, not a copy of the runner's source.

There are two prompts that can produce a script: the legacy planner's script
section (`planner.PLANNER_PROMPT`) and the L3 script prompt
(`l3_planner._SCRIPT_SYSTEM_PROMPT`), which is the one the live path uses when
`USE_L3_PLAN_LAYER` is on. BOTH MUST carry the same facts. Fixing one and
leaving the other stale is the failure this requirement exists to prevent: the
L3 prompt told the model "this is the whole surface" and named only the six
original calls (the count before `api.result` was added), so a bot on the live
path could not see `look` or `api.result`
at all (seen live 2026-11-21). The two MUST share one text so they cannot drift
apart.

#### Scenario: The rendered prompt names every call, with its shape
- **GIVEN** a planner prompt rendered for a goal
- **WHEN** a script is offered as an answer
- **THEN** the prompt MUST name `look.blocks(kind, options)`,
  `look.entities(type, options)` and `look.age()` with the arguments and the
  return shape the runner binds (`{ ok, matches }`, or `{ ok: false, reason }`)
- **AND** it MUST name `api.result(v)` with what it returns (`{ ok: true }` or a
  rejection)
- **AND** a prompt that no longer names either call MUST fail this scenario

#### Scenario: The prompt states the snapshot's radius limits
- **GIVEN** the planner prompt's `look` description
- **WHEN** it states how far a script can see
- **THEN** it MUST give the real radii, blocks 5 and entities 16
- **AND** it MUST say that a query beyond them answers "not searched that far"
  rather than an empty list
- **AND** it MUST say the answers describe the tick's snapshot, not a live
  query

#### Scenario: The prompt states the result's journey
- **GIVEN** the planner prompt's `api.result` description
- **WHEN** it states what happens to a reported value
- **THEN** it MUST say the value reaches the planner when the script ends
  (`done`, an error, or `escalate`)
- **AND** it MUST say the last call in a tick wins
- **AND** it MUST say the value is cut at 2 KiB with a truncation marker
- **AND** it MUST say the script's top-level return value is discarded and is
  not the result

#### Scenario: The prompt counts only the calls that are host calls
- **GIVEN** the prompt's line about the per-tick host-call budget
- **WHEN** it says which calls spend it
- **THEN** `api.result` MUST be counted among the eight
- **AND** `look` MUST NOT be counted, because it answers from data already in
  hand

#### Scenario: The L3 script prompt carries the same surface
- **GIVEN** the L3 script prompt rendered for a goal, as `call_script` renders
  it
- **WHEN** the model is asked for a script on the live path
- **THEN** the rendered prompt MUST name `look.blocks(`, `look.entities(`,
  `look.age(` and `api.result(`
- **AND** it MUST carry the same facts as the planner prompt: blocks 5 and
  entities 16, a beyond-range query answering "not searched that far", the
  snapshot not being live, `look` free and `api.result` one of the eight host
  calls, delivery on done/error/escalate, the last call winning, the 2 KiB cut,
  and the top-level return value not being the result
- **AND** it MUST NOT tell the model to report by returning an array of
  actions, because the runner discards a script's return value
- **AND** dropping either prompt's copy of the surface, or letting the two
  diverge, MUST fail this scenario

#### Scenario: The prompt says when to use them
- **GIVEN** the planner prompt's `look` description
- **WHEN** it tells the planner when to choose a lookup
- **THEN** it MUST say to look before acting on a block the bot has to be near
- **AND** the `api.result` description MUST say to report what a goal found, or
  why it stopped

### Requirement: A Lookup Reads The World Where The Envelope Puts It

A lookup MUST read the tick's world data from the path the agent actually
sends, not from a shape assumed beside it. The tick request's `snapshot` is the
envelope built by `snapshot.build_envelope` (`agent/snapshot.py`), which is
`{"tick", "server_ms", "state", "events", "task"}`; the world a lookup answers
from is `snapshot.state.nearby`, with `blocks` and `mobs` beneath it. A lookup
that reads `snapshot.nearby` directly answers from `undefined` and MUST NOT
report that as an empty world.

An empty `matches` list MUST mean "I looked where the snapshot covers and there
was nothing" and MUST NOT be returned because the lookup read the wrong path.
The failure this requirement exists to stop was silent: every lookup returned
`{ok: true, matches: []}` on a snapshot that carried the block and the mob, so
two scripts idled while the trigger was in front of them, and nothing reported
an error.

Tests for this requirement MUST build their snapshot through the agent's own
envelope constructor, or assert against its output, so a fixture cannot drift
into a shape the game never sends. A hand-written fixture that happens to match
the lookup's assumption is not evidence about the live path.

The values **under** those keys are lists, and the agent MUST put them there as
lists. The game's HTTP handlers wrap every observation in a one-key object —
`{"blocks": [...]}` from `/bot/{name}/blocks`, `{"entities": [...]}` from
`/bot/{name}/entities`, `{"inventory": [...]}` from `/bot/{name}/inventory`
(`HttpApiServer.java:469`, `:504-505`) — and `snapshot.build_state`
(`agent/snapshot.py`) stores those responses unchanged. A lookup therefore
receives an object where it requires an array and MUST NOT answer that as an
empty world.

`build_state` MUST unwrap the game's response: when the value is a mapping it
MUST take the list under the expected key, when the value is already a list it
MUST keep it, and anything else MUST become an empty list **and** append a
reader error rather than pass silently. This is the same failure one level
down from the depth bug above, and it was silent in the same way: the legacy
planner already unwraps these responses in `prompts.py`, which is why the
planner saw the world while every script saw nothing.

#### Scenario: The world is found where the envelope puts it
- **GIVEN** a tick whose snapshot is the real envelope, carrying
  `state.nearby.blocks` with an `iron_ore` entry and `state.nearby.mobs` with a
  `sheep` entry
- **WHEN** the script calls `look.blocks('iron_ore')` and
  `look.entities('sheep')`
- **THEN** each MUST return `ok: true` with one match
- **AND** neither MUST return an empty list

#### Scenario: The fixture is the producer's own output
- **GIVEN** a test of the lookup
- **WHEN** its snapshot fixture is built
- **THEN** it MUST come from `snapshot.build_envelope`, or be asserted equal to
  what that function produces
- **AND** a fixture written by hand to the shape the lookup happens to read
  MUST NOT be accepted as covering the live path

#### Scenario: Running build_envelope is not enough if its input is invented
- **GIVEN** a fixture generated by calling `build_envelope`
- **WHEN** the values fed into it are the ones the game sends
- **THEN** every position MUST be an `{x, y, z}` map, because
  `BotPlayer.formatPos` returns `Map<String,Double>` and
  `NearbyBlockIndex.positionOf` returns `Map<String,Integer>`
- **AND** a field the Java itself formats as a string, such as the entity
  `distance` (`String.format("%.1f", ...)`) MUST stay a string
- **AND** a fixture whose values were hand-written to a shape the game does not
  send MUST NOT pass merely because it went through `build_envelope`

Passing hand-written inputs through the producer's function launders them: the
file then records a wrong shape faithfully, and every lookup test reading it
agrees with the mistake. A regenerated fixture MUST equal the committed bytes,
so a hand-edit or a shape regression fails a test instead of passing quietly.

The envelope's capture time is `server_ms`. A lookup that reports the
snapshot's age MUST read that field; reading a field the envelope does not
carry MUST NOT be reported as "the game sent no capture time", because it did.

#### Scenario: The snapshot's age comes from the envelope's own stamp
- **GIVEN** a snapshot carrying `server_ms` and no other timestamp field
- **WHEN** the script asks the snapshot's age
- **THEN** the answer MUST carry an `ageMs` number derived from `server_ms`
- **AND** it MUST NOT answer `null` with "the game sent no capture time"

#### Scenario: The wrong depth is detectable
- **GIVEN** an implementation that reads `snapshot.nearby` while the envelope
  nests the world at `snapshot.state.nearby`
- **WHEN** the lookup runs against the real envelope
- **THEN** the first scenario MUST fail
- **AND** the failure MUST name an empty match list rather than an error, so the
  test that catches it is the scenario above and not an exception

#### Scenario: The game's wrapped response becomes a list
- **GIVEN** an API whose `blocks()` returns
  `{"blocks": [{"id": "minecraft:iron_ore", "block": "Iron Ore", "position": …}]}`
  and whose `entities()` returns
  `{"entities": [{"type": "sheep", "name": "Sheep", "position": …}]}`
- **WHEN** `snapshot.build_state` builds the state
- **THEN** `state.nearby.blocks` MUST be a list holding that one block entry
- **AND** `state.nearby.mobs` MUST be a list holding that one sheep entry
- **AND** `look.blocks('minecraft:iron_ore')` MUST return one match from that
  snapshot

#### Scenario: A bare list is tolerated
- **GIVEN** an API whose `blocks()` returns a list directly rather than a
  wrapper
- **WHEN** `snapshot.build_state` builds the state
- **THEN** `state.nearby.blocks` MUST be that list, unwrapped and unchanged

#### Scenario: An unusable shape is a reader error, not silence
- **GIVEN** an API whose `blocks()` returns a string or a number
- **WHEN** `snapshot.build_state` builds the state
- **THEN** `state.nearby.blocks` MUST be an empty list
- **AND** the state's errors MUST name the `blocks` reader, so the tick reports
  a broken observation rather than a world with nothing in it

#### Scenario: Every reader sees the same unwrapped shape
- **GIVEN** a reader of `state.nearby` other than the lookup (the legacy
  planner's prompt, a diagnostic, a tool script)
- **WHEN** it reads `state.nearby.blocks` or `state.nearby.mobs`
- **THEN** the value it sees MUST be the same list the lookup reads
- **AND** no reader MUST be left handling a wrapper the agent no longer stores

### Requirement: A Script That Needs World Time Reads It, Never Estimates It

The snapshot MUST carry the real day time of the level the bot is IN, and a script
that needs a time-of-day fact MUST read that field rather than derive one. (The
bot's own level, not the overworld's: lighting is per-dimension, so reporting
the overworld's clock to a bot in the Nether would be the same class of lie this
requirement exists to prevent.)

A time-of-day fact is state, not a computation the script may perform. Lighting
is per-dimension and per-level, and the time the game keeps is the only
authority on whether it is dark; a script that reconstructs it from the tick
count is inventing a clock. On 2026-11-22 prod Mystic told a player "It's getting
dark — overworld time is 0 (night)" — the truthful reading was daytime —
because the snapshot carried no time, the prompt described a schema the envelope
never had, and the script fell back to `(6000 + ticks*10) % 12000`, which reaches
0 after 600 ticks. It also counted 0..1000 as night, and 0 is sunrise.

The mod's `GET /bot/{bot}/status` MUST report `day_time` — the bot's own level's
`level.getDayTime() % 24000` — and `is_night`, a boolean derived from it. The
agent MUST carry both into `state.world` as `{day_time, is_night}`, so the
nesting matches the rest of the state (`snapshot.state.world.day_time`) rather
than sitting at a level the envelope does not use.

The planner prompt MUST state the snapshot's exact shape — field names and
nesting — so a script is written against what the agent sends. A prompt that
names fields the envelope does not carry is the defect this requirement exists to
prevent, not a simplification of it.

When a script needs a fact the snapshot does not carry, it MUST NOT estimate,
derive or invent it. It MUST either report `done: false` with a reason, or fail
the goal and say so in chat. A plausible wrong answer is worse than a refusal,
because the player cannot tell it from the truth.

#### Scenario: A wait-for-dark script announces only on the real field
- **GIVEN** a snapshot carrying `state.world.day_time` and `state.world.is_night`
- **WHEN** a script waiting for nightfall reads the snapshot
- **THEN** it MUST decide from `state.world.is_night` and MUST NOT derive night
  from the tick count, a modulus, or any field the envelope does not carry
- **AND** it MUST announce only when `is_night` is true
- **AND** across a full day cycle it MUST make exactly one announcement, so a
  script that counts 0..1000 as night cannot pass by firing at sunrise

#### Scenario: The status carries real day time from the level
- **GIVEN** a level whose `getDayTime()` is 15000 (afternoon, daylight is ending)
- **WHEN** the status is built for that bot
- **THEN** it MUST carry `day_time` 15000 and `is_night` true
- **AND** at `getDayTime()` 1000 (morning) it MUST carry `is_night` false
- **AND** a `getDayTime()` above 24000 MUST be reduced modulo 24000, so a level
  that has run for several days does not report an out-of-range time

#### Scenario: The prompt describes the shape the agent actually sends
- **GIVEN** the planner prompt rendered for a script request
- **WHEN** its snapshot schema is compared with the envelope `build_state`
  produces
- **THEN** every field the prompt names MUST exist at the path the prompt gives
- **AND** the prompt MUST name `state.world.day_time` and `state.world.is_night`
- **AND** a field the envelope does not carry MUST NOT be presented as readable

#### Scenario: A missing fact is refused rather than invented
- **GIVEN** a goal requiring a fact the snapshot does not carry
- **WHEN** the script runs
- **THEN** it MUST report `done: false` with a reason, or fail the goal and say
  so in chat
- **AND** it MUST NOT emit a plausible substituted value (an estimated time, a
  guessed position, a default count)

### Requirement: A Directive Missing A Required Field Is Refused, Never Dispatched

An action MUST be refused at binding when it lacks a field its kind requires,
with a reason the script log shows, on the same path as an unknown kind. It
MUST NOT reach the mod. A malformed directive MUST fail the directive or be
refused — never leave a bot wedged or spam the server thread.

The failure this requirement exists to stop: on 2026-11-22 a script dispatched
`MINE {"kind": "MINE", "x": 16, "y": 89, "z": -16}` with no `target`.
`_ALLOWED_ARGS` admits `x`, `y` and `z` for every kind (`_ALLOWED_ARGS` in `agent/action_binding.py`),
so binding passed it. The mod's `BotBrain.applyDirective` installed `MineBehavior`
before calling `start()` (`BotBrain.java:169-170` before this change);
`MineBehavior.start()` reads `directive.getTarget()` (`MineBehavior.java:71`
before this change) and calls `resolveDrop(targetBlock)` on it (`:83`) before
`enterPhase()` (`:94`), which NPEs on null. Because the behavior was already
installed, every server tick hit `switch (phase)` at `:107` and NPEd again: 312 stack traces in ~16 s, the server
thread fell behind, and the bot stopped answering (`/brain` timed out at 10 s,
L1 polls at 5 s) for more than eight minutes. Other bots were unaffected.

`bind_action` MUST validate per-kind required fields. At minimum, `MINE`
requires a non-blank `target`, and its `x`/`y`/`z` are NOT coordinates — a lookup
returns positions, so a script mines a found block by passing the entry's
`block` (or `id`) as `target` with a `count`. The per-kind field table MUST
carry each kind's required fields and MUST be pinned by a test, in the pattern
of `test_bindable_set_matches_source`, so the table and the check cannot drift.

The script prompt MUST document the required fields of the common kinds,
derived from that same table rather than hand-written, so a planner is told
what to send instead of discovering it through a refusal.

Defence in depth in the mod, which MUST hold even when a caller bypasses the
agent's binding: `BotBrain.applyDirective` MUST NOT leave a half-started
behavior — if `start()` throws, the directive fails with a reason logged once
and the bot falls back to idle, rather than retrying a throwing `tick()` every
server tick. `MineBehavior.start()` MUST reject a null or blank target cleanly
before `resolveDrop`.

#### Scenario: MINE without a target is refused and the bot stays responsive
- GIVEN a script that dispatches `{"kind": "MINE", "x": 16, "y": 89, "z": -16}`
- WHEN the tick binds the action
- THEN the action is refused with a reason naming the missing `target`
- AND the script log shows that reason
- AND no directive reaches the mod
- AND the bot answers its next brain poll

#### Scenario: A throwing start() degrades the directive, not the server
- GIVEN a behavior whose `start()` throws
- WHEN `applyDirective` installs it
- THEN the directive is marked failed and its reason logged once
- AND the bot falls back to idle
- AND no further `tick()` on that behavior runs

#### Scenario: The prompt names the fields MINE requires
- GIVEN the rendered script prompt
- WHEN a planner reads the `MINE` entry
- THEN it says `target` (a non-blank block id) is required
- AND it says `target` is never a position, so `x`/`y`/`z` do not stand in for it
- AND the field names in the prompt come from the same table the binding checks

### Requirement: A Directive Needing Coordinates Is Refused Without Them

A kind whose coordinates are always meaningful MUST be refused at binding when
it omits `x`, `y` or `z`, with a reason the script log shows. It MUST NOT bind
and act on an implied origin.

The failure this requirement exists to stop: `Directive`'s `x`, `y` and `z` are
primitive doubles defaulting to `0.0`
(`src/main/java/com/sigmastrain/aiplayermod/brain/Directive.java:86`), and
`hasLocation` is set only by the builder's `location(...)` (`:98-100`).
`GOTO` and `TELEPORT` read `directive.getX()` unconditionally in `start()`
(`GotoBehavior.java:36-38`, `TeleportBehavior.java:22-24`), so a script sending
`{"kind": "GOTO"}` with no coordinates binds, and the bot walks to — or
teleports to — `0,0,0`, including into another dimension for `TELEPORT`. It does
not throw and is bounded by `MAX_TICKS`, so it is less severe than the MINE
wedge, but it is still an action the script never asked for.

The rule applies to a kind only where a missing coordinate is never valid. Every
bindable kind that reads directive coordinates was checked:

- `GOTO`, `TELEPORT` — read `getX()`/`getY()`/`getZ()` with no `hasLocation()`
  guard, in `start()`. Refused without coordinates.
- `BUILD` — `BuildBehavior.java:99-107` treats an all-zero location as "build
  here", building at the player's feet. A missing coordinate IS valid here, so
  `BUILD` is deliberately NOT in the rule; adding it would refuse a working call.
- `WIDE_SEARCH` (`WideSearchBehavior.java:92-97`), `AREA_LOOT`
  (`AreaLootBehavior.java:102-110`), `FUSE_BLOCK` (`FuseBlockBehavior.java:80`),
  `DRIVE_VEHICLE` (`DriveVehicleBehavior.java:42`), `STORE_ALL`
  (`StoreAllBehavior.java:63`), `CONTAINER_STORE`
  (`ContainerStoreBehavior.java:89`), `CONTAINER_WITHDRAW`
  (`ContainerWithdrawBehavior.java:68`) — each reads coordinates only under
  `hasLocation()` and otherwise falls back to the bot's position or `extra`.
  Left alone: their missing-coordinate behaviour is a deliberate fallback.
- Every other bindable kind does not read directive coordinates at all.

The coordinate rule MUST be a per-kind table, pinned by a test against this
enumeration, so a new kind that reads coordinates unguarded is a test failure
rather than a silent walk to origin. The script prompt MUST say which kinds need
`x`/`y`/`z`, from that same table.

A kind may require `target` and coordinates both; the two tables are separate
because they answer different questions.

#### Scenario: GOTO without coordinates is refused, not walked to origin
- GIVEN a script that dispatches `{"kind": "GOTO"}`
- WHEN the tick binds the action
- THEN it is refused with a reason naming `x`, `y` and `z`
- AND the script log shows that reason
- AND no directive reaches the mod
- AND no bot moves

#### Scenario: TELEPORT without coordinates is refused
- GIVEN a script that dispatches `{"kind": "TELEPORT", "extra": {"dimension": "minecraft:the_nether"}}`
- WHEN the tick binds the action
- THEN it is refused with a reason naming `x`, `y` and `z`
- AND the bot is not teleported

#### Scenario: BUILD with no coordinates still builds where the bot stands
- GIVEN a script that dispatches `{"kind": "BUILD", "target": "shelter"}`
- WHEN the tick binds the action
- THEN it binds
- AND the mod builds at the bot's position, as its all-zero fallback intends

#### Scenario: Coordinates that are present and real bind
- GIVEN a script that dispatches `{"kind": "GOTO", "x": 16, "y": 89, "z": -16}`
- WHEN the tick binds the action
- THEN it binds
- AND the bound action carries all three coordinates

#### Scenario: A zero coordinate is a coordinate
- GIVEN a script that dispatches `{"kind": "GOTO", "x": 0, "y": 64, "z": 0}`
- WHEN the tick binds the action
- THEN it binds
- AND the refusal is about an absent coordinate, never about one that equals zero

#### Scenario: The prompt says which kinds need coordinates
- GIVEN the rendered script prompt
- WHEN a planner reads it
- THEN it names `GOTO` and `TELEPORT` as needing `x`, `y` and `z`
- AND the kinds it names come from the same table the binding checks

### Requirement: A Script Can Read The Bot's Own Body

A script MUST be able to read the bot's own position, health and food level from
the same snapshot every other lookup answers from, without a host call.

The agent already sends these: `snapshot.build_state` (`agent/snapshot.py`)
places `health`, `food` and `position` at the top level of `state`, read from the
game's `/bot/{name}/status` (`BotPlayer.getStatus`, `BotPlayer.java:755-762`).
`position` is `{x, y, z}` as numbers, rounded to one decimal
(`formatPos`, `BotPlayer.java:1235-1240`); `health` and `food` are numbers.

The lookup MUST be `look.self()`, returning `{ok: true, position, health, food}`,
and MUST read `snapshot.state`, not any other path. A script that guesses a
shape the envelope does not carry MUST NOT be left to fail silently.

The document that lists the script surface MUST name `look.self()` with its
returned fields, in the same form as the existing `look` calls, so a planner
does not have to guess how to read the bot's own position.

Trial 4.3 (2026-11-22, bot Axiom, script `b6e61fbe`) is the failure this
requirement exists to stop: a script issued `GOTO x=-15 y=77 z=-28`, then
checked arrival with `snapshot.self.position` — a path that does not exist. The
bot reached `(-13.7, 77.4, -27.5)`, the check never passed, and the script
re-sent the identical GOTO every tick, each one COMPLETED.

#### Scenario: A script reads its own position from the real envelope
- **GIVEN** a tick whose snapshot is the real envelope, carrying
  `state.position` of `{x: -13.7, y: 77.4, z: -27.5}`, `state.health` and
  `state.food`
- **WHEN** the script calls `look.self()`
- **THEN** it MUST return `ok: true` with that `position` and those numbers
- **AND** it MUST NOT read `snapshot.self` or any path the envelope lacks

#### Scenario: Trial 4.3's arrival check passes when the bot has arrived
- **GIVEN** the envelope above, where the bot is within three blocks of
  `(-15, 77, -28)`
- **WHEN** a script checks `look.self().position` against that target within
  three blocks
- **THEN** the check MUST pass, so the script does not re-issue the GOTO

#### Scenario: The prompt names look.self and its fields
- **GIVEN** the rendered script prompt
- **WHEN** a planner reads it
- **THEN** it names `look.self()` and says it returns `position`, `health` and
  `food`

### Requirement: A Repeatedly Completed Identical Action Yields The Goal

A script that re-dispatches the SAME action that has already COMPLETED, N times
in a row, MUST yield the goal back to the planner and MUST log why, rather than
re-issuing it forever.

The signal is the identical action completing again, not a diff of world state.
Position, ages and mob health all move between ticks for reasons unrelated to
whether the action worked, so a state-equality test would either fire on a
slow action making progress or stay silent on a spin. An identical completed
action is the thing that is actually wrong: the script asked for the same work
it has already been told is done, which means its own completion check is not
firing (trial 4.3), and no amount of re-issuing resolves that.

N is `SCRIPT_REPEAT_MAX = 5`. The bound is a recovery from a script whose own
check is broken, not a retry policy: a legitimate action that needs more than
five identical completed re-issues to show progress is one whose completion
test is measuring something other than what it acts on, and the planner is
better placed to see that than the tick loop. The count is per identical
action: a different action resets it, so a script alternating between two
useful steps is not counted as a spin.

Yielding on a spin MUST reuse the all-refused yield path: unbind the script,
drop the step list, and re-submit the goal to the planner under
`SCRIPT_REPLAN_MAX`, so a spinning script cannot re-plan forever either. The
yield MUST log the action and the count.

Trial 4.3 is the case: the identical GOTO was re-sent ten or more times, each
COMPLETED, and nothing yielded until a human restarted the agent.

#### Scenario: Trial 4.3's repeated GOTO yields the goal, by count
- **GIVEN** a script that dispatches `GOTO x=-15 y=77 z=-28`
- **AND** that identical action COMPLETES on each tick with no different action
  between
- **WHEN** it has COMPLETED `SCRIPT_REPEAT_MAX` times in a row
- **THEN** the goal MUST be yielded to the planner
- **AND** the yield MUST log the action and the count
- **AND** the script MUST NOT dispatch it an `(N+1)`th time

#### Scenario: A different action resets the count
- **GIVEN** a script that dispatches the same GOTO four times, then a MINE
- **WHEN** it dispatches the GOTO again
- **THEN** that GOTO MUST be the first of its run, not the fifth
- **AND** it MUST NOT yield

#### Scenario: The bound does not fire before N
- **GIVEN** the same action COMPLETED `N-1` times in a row
- **WHEN** the next tick dispatches it again
- **THEN** it MUST NOT yield yet

#### Scenario: A yielding spin is still bounded by the re-plan count
- **GIVEN** a goal whose script spins, yields, and whose planner answers with
  the same spinning script
- **WHEN** it has been re-submitted `SCRIPT_REPLAN_MAX` times
- **THEN** it MUST stop re-planning, exactly as an all-refused yield does

### Requirement: A Script Can Read The Directive's Result

A script MUST be able to read what the directive it dispatched has reported,
including on the tick after it completes. `api.do` answers `{ok, seq}`
(`agent-script-runner/src/binding.js:324`), which says the action was ACCEPTED
and carries no progress, so a script that checks a completed action had no
route to its outcome at all. That is review F-1 on `465b61e`: the GOTO emitted
`arrived_at` correctly, and no script could see it.

The lookup is `look.task()`, read from `state.task`. `state.task` IS the mod's
whole `GET /bot/{name}/directive` body (`HttpApiServer.java:1338` answers it with
`BotBrain.toMap()`, `BotBrain.java:213-230`), so it carries the directive
(`Directive.toMap()`) AND `progress` (`ProgressReport.toMap()`), and
`progress.result` is where a behaviour's `putResult` fields land. Passing only
the inner `directive` map here is what made `result` unreadable, and the
envelope's `events` field is NOT the carrier: nothing populates it
(`build_envelope` in `agent/snapshot.py` defaults it to `[]` and no caller passes it).

`look.task()` MUST return `{ok: true, id, type, status, result, phase,
failure_reason}`:
- `id`, `type`, `status` come from the directive, so a script can tell WHICH
  directive finished and whether it `COMPLETED` or `FAILED`. `status` is the
  field to trust for "is it done" -- `ok` from `do` never means that.
- `result` is the directive's `progress.result` map. It MUST be an empty object,
  not `undefined`, when the directive has reported nothing, so reading
  `result.arrived_at` is `undefined` rather than a throw.
- With no snapshot the answer is `{ok: false, reason: "no-snapshot"}`; with no
  directive it is `{ok: true, id: null, type: null, status: null, result: {},
  phase: null, failure_reason: null}` -- the SAME key set as the populated
  branch, with every value null or empty. These are different facts and MUST
  NOT be reported as each other (no-snapshot is `ok: false`).
- `look.task()` MUST NOT nest a `directive` key on either branch. The idle
  branch used to emit `{directive: null, ...}` while the populated branch
  emitted the directive's fields at the top level, so a script written against
  `task.directive` saw a running directive as `undefined` and an idle bot as
  an object -- the reading was inverted, and trial 4.2's retry hung on it
  (Forge waited for `task.directive === "GOTO"` forever while its GOTO ran).
  The kind is `task.type`; the completion is `task.status`.

`SCRIPT_SURFACE` MUST document `look.task()`, naming `result` and the fields a
completed action puts there. It MUST NOT tell a script to write an arrival check
against a field no lookup returns.

#### Scenario: A script sees where its GOTO arrived
- **GIVEN** a script that dispatched `GOTO` and on a later tick reads
  `look.task()`
- **WHEN** the directive has completed at a destination that was lifted
- **THEN** `status` MUST be `COMPLETED`
- **AND** `result.arrived_at` MUST be the `{x, y, z}` the bot actually reached
- **AND** `result.adjusted_from` MUST name the coordinates requested and
  `result.adjusted_to` the lifted ones

#### Scenario: A failed directive's reason reaches the script
- **GIVEN** a `GOTO` that failed with `target_enclosed`
- **WHEN** the script reads `look.task()`
- **THEN** `status` MUST be `FAILED`
- **AND** `failure_reason` MUST start with `target_enclosed`

#### Scenario: An idle bot reports no directive, not a missing snapshot
- **GIVEN** a snapshot whose `state.task` is `null`
- **WHEN** a script calls `look.task()`
- **THEN** it MUST return `ok: true` with `id`, `type`, `status`, `phase` and
  `failure_reason` all `null` and `result` an empty object -- the same key set
  a populated answer has, so one wait condition works against both

### Requirement: An Idle Script Yields Only A Goal It Actually Has, And Only When Nothing Is Running

A script that dispatches nothing, tick after tick, MUST NOT be able to hold a
goal forever -- trial 4.2's retry waited on a completion it could not read and
never dispatched again. The bound on that is `SCRIPT_IDLE_MAX` consecutive
ticks, after which the goal is yielded to the planner like a repeated action.

The bound MUST apply only where yielding means something, in two ways.

First, a bot with NO active goal has nothing to yield. A script bound from
`bindings.json` survives `_unbind_planner_script` by design and `_script_hold`
only clears when the goal ends, so a hand-written script on a goal-less bot is
reachable. Yielding there unbinds nothing, clears a live `_plan_steps`, and
resubmits an empty goal -- every `SCRIPT_IDLE_MAX` ticks, forever. With no
goal, the idle line is the correct output and nothing else MUST happen. Such a
tick MUST NOT even be COUNTED (the `if not self._has_active_goal(): return False` branch that guards `_note_script_idle_tick`, `agent/agent.py`): climbing to the bound,
resetting and climbing again is the same unbounded repeat in a quieter form.
The log MUST NOT say a goal was unfinished unless one exists: the same
predicate decides both, so they cannot disagree.

The refusal MUST live in the yield itself, not only at the idle caller. The
idle path returns before the counter, so it never reaches the yield; the SPIN
caller does, and arrives goal-less for the same reasons. Guarding the callee
covers all three callers with one predicate, so they cannot disagree about
whether a goal exists.

Second, a tick where the bot's own directive is still running is NOT idle. A
script polling a 30-block `GOTO` dispatches nothing on every tick of the walk;
counting those would yield the goal mid-walk, replacing the wait the script
wants with a re-plan it does not. A directive counts as in progress when
`look.task()` reports it with status `ACTIVE` (`DirectiveStatus`,
`Directive.java:22`); a `COMPLETED` directive is a result to read, not work in
flight. Such a tick MUST NOT advance the idle run. The status is read from the
envelope that same tick already built, recorded as `ScriptTick.last_task`
(`ScriptTick.last_task`, set in `agent/script_tick.py`), not from a second request: a fresh `GET` would answer
for a different moment than the script was given.

Third, and overriding the second where they disagree, an `ACTIVE` directive
MUST NOT be able to hold a goal forever. The in-progress gate is what stops a
legitimate walk being torn down, but it is also a hole: a behaviour with no
terminal exit keeps its status `ACTIVE` indefinitely, so the idle bound can
never fire. `FOLLOW` is the demonstrated case -- it returns `RUNNING` for every
PRESENT target (`FollowBehavior.java:94`, `:99`, `:107`) and its only terminal
exit (`OFFLINE_GIVEUP_TICKS`, `:31`, gated at `:66`) requires the target
ABSENT -- and a script may issue it, since `MOD_DIRECTIVE_KINDS` in `agent/action_binding.py` admits
`FOLLOW`. After `SCRIPT_DIRECTIVE_MAX_TICKS` consecutive `ACTIVE` ticks the
goal MUST be yielded for re-planning, with a log line naming the bound and
saying the directive produced no terminal result. The directive itself MUST
NOT be cancelled: the bound is on the wait, not the work, so a re-plan may
re-issue it and it then stops counting. The run MUST be reset whenever no
directive is in flight, so the bound is on CONSECUTIVE ticks and not a total.
It MUST also be reset by any tick that dispatches an action: a dispatched
action is new work, so a directive still `ACTIVE` afterwards is a new wait
rather than the continuation of the one being bounded -- otherwise a script
issuing a directive every tick would accrue to the bound while making progress.
The bound MUST be set per directive type, above that type's own longest
legitimate run, because behaviours do not share a unit: `GOTO` bounds itself
at `MAX_TICKS = 600` (`GotoBehavior.java:37`), while `COMBAT` defaults to 6000
ticks (`CombatBehavior.DEFAULT_DURATION`, `:68`, and more when a count is
given) and `FOLLOW` against a present player has no bound at all. A single
number large enough for `COMBAT` would never fire on `FOLLOW`; one small
enough for `FOLLOW` would cut a working `COMBAT` in half. A type absent from
the table MUST get the largest bound, so it is bounded loosely rather than
not at all.

#### Scenario: A goal-less bot does not yield
- **GIVEN** a bound script that dispatches nothing and no active goal
- **WHEN** `SCRIPT_IDLE_MAX` consecutive ticks pass
- **THEN** `_plan_steps` MUST be unchanged
- **AND** the script MUST stay bound
- **AND** the log MUST NOT claim a goal was unfinished

#### Scenario: A walk in progress is not idleness
- **GIVEN** a script that dispatches nothing while its directive reports `ACTIVE`
- **WHEN** many ticks pass, more than `SCRIPT_IDLE_MAX` but fewer than `SCRIPT_DIRECTIVE_MAX_TICKS`
- **THEN** the goal MUST NOT be yielded
- **AND** the idle run MUST NOT reach the bound while the directive runs

#### Scenario: A directive that never goes terminal yields the goal
- **GIVEN** a bound script with an active goal whose directive stays `ACTIVE`
- **WHEN** `SCRIPT_DIRECTIVE_MAX_TICKS` consecutive ticks pass
- **THEN** the goal MUST be yielded to the planner
- **AND** the directive MUST NOT be cancelled
- **AND** the log MUST name the bound (trial 4.2's wait-that-cannot-end, one layer down)

#### Scenario: Bounded behaviour never trips the directive bound
- **GIVEN** a `GOTO` that runs to its own `MAX_TICKS = 600` limit
- **WHEN** the script polls it to completion
- **THEN** `SCRIPT_DIRECTIVE_MAX_TICKS` MUST NOT have been reached
- **AND** the goal MUST NOT be yielded before the walk finishes

#### Scenario: A productive script does not accrue to the bound
- **GIVEN** a script that dispatches an action on every tick, each leaving a directive `ACTIVE`
- **WHEN** more than `SCRIPT_DIRECTIVE_MAX_TICKS` ticks pass in total
- **THEN** each dispatch MUST restart the ACTIVE run
- **AND** the goal MUST NOT be yielded

### Requirement: A Finished Directive Stays Readable Until The Next One

`look.task()` MUST keep answering for a directive that has finished
(`COMPLETED`, `FAILED` or `CANCELLED`), with its own `status` and `result`,
until a different directive is dispatched. A script waits for its own work to
finish; if the answer vanishes at the moment it becomes `COMPLETED`, the script
can never observe the transition it is polling for.

Trial 4.2 retried on TEST (2026-11-22 04:28Z) hung exactly this way: the script
dispatched `GOTO (-139, -35, -151)`, the mod completed it, and every subsequent
`look.task()` saw no directive, so the wait condition
`type === 'GOTO' && status === 'COMPLETED'` was never once true and the bot
idled until the agent was restarted.

The mod ALREADY retains the terminal directive: `BotBrain.toMap()` answers from
`lastDirective`/`lastProgress` once `activeDirective` is null
(`BotBrain.java:222-225`), which the `lastDirective` fallback in `agent/agent.py` relies on -- that branch is
the "Directive lost after connection errors" fallback, which is only safe
because the mod answers from `lastDirective`. The retention was destroyed by
the agent, not the mod: on seeing `COMPLETED` the L1 poller called
`api.cancel_directive`, and `BotBrain.cancelDirective` clears all three
retention fields (`BotBrain.java:62-64`). Those calls are REMOVED by this
change, so the line numbers moved with them: the `COMPLETED` branch's now-gone
cancel sat immediately before the `print(f"...Directive COMPLETED...")` at
the `Directive COMPLETED` print in `agent/agent.py`, and the `FAILED`/`CANCELLED` branch is `elif status in ("FAILED", "CANCELLED")` in the same function.
The fix belongs where the damage was: a completion or failure that the agent
has FINISHED observing MUST NOT be followed by a cancel that wipes the record
the scripts read. Cancellation for a directive still running (stuck,
interrupted, user requested) is unaffected and MUST keep clearing, because
that directive has no terminal outcome to retain.

This requirement is about OBSERVABILITY, not about the directive's life. The
bot is idle either way; what changes is whether a script can see that its work
ended and where.

#### Scenario: A script sees its GOTO complete, then acts
- **GIVEN** a script waiting on `type === 'GOTO' && status === 'COMPLETED'`
- **WHEN** the GOTO's last tick returns SUCCESS
- **THEN** on at least the next tick `look.task()` MUST report that directive
  with `status` `COMPLETED`
- **AND** it MUST keep reporting it until a different directive is dispatched

#### Scenario: The retained record survives a full poll cycle
- **GIVEN** a directive the agent has observed complete
- **WHEN** the agent's poll loop finishes handling that completion
- **THEN** a read of `GET /bot/{name}/directive` MUST still carry the directive
  and its `progress.result`
- **AND** this MUST be tested against the real post-completion body, not only
  a hand-made fixture

#### Scenario: A cancelled running directive is still cleared
- **GIVEN** a directive cancelled while still ACTIVE (stuck, interrupted)
- **WHEN** the cancel completes
- **THEN** `look.task()` MUST NOT report that directive afterwards

### Requirement: GOTO Fails Rather Than Silently Relocating An Enclosed Target

A `GOTO` whose target block is enclosed MUST fail with the reason
`target_enclosed` rather than move the target to somewhere reachable. A GOTO
that arrives somewhere other than where it was sent, and reports COMPLETED, is
the failure: the caller cannot tell that the destination changed.

`GotoBehavior.start` (`GotoBehavior.java:57`) resolves the target through
`decideLift` (`:122`), which raises `targetY` one block at a time until the feet
and head are clear. Before this change the loop stopped only at the build
limit. For a target inside solid rock that walks the destination to the
surface: trial 4.2 (2026-11-22, test server) sent `GOTO (-123, -44, -152)`, an
enclosed `deepslate_diamond_ore`, and the bot was sent to `y = -8`, 36 blocks
above, through a different cave.

The search MUST be bounded to `GOTO_MAX_LIFT = 3` blocks above the target. A
few blocks covers a target buried under a floor or under a shallow ledge, which
is a real intent. Beyond that the caller meant that exact place, and moving it
36 blocks is not an adjustment but a different destination.

If no clear standing position exists within that bound, the directive MUST fail
with reason `target_enclosed`, naming the requested coordinates, rather than
walking, climbing or teleporting anywhere else. A silent substitution is the
defect this requirement exists to stop, so an adjustment is only acceptable
when it is bounded AND reported (below).

When the target IS lifted within the bound, the COMPLETED result MUST carry the
actual arrival position and an `adjusted_from` field naming the coordinates
that were asked for, so a script's own arrival check can be written against
what happened rather than what it requested. The result MUST ride the existing
`ProgressReport.putResult` channel. That channel has two consumers and they are
NOT the same: the `Directive COMPLETED` observer line in `agent/agent.py` renders it into a `COMPLETED <type> {...}
result={...}` line for the PLANNER, and `look.task()` reads it back to the
SCRIPT (see "A Script Can Read The Directive's Result"). Emitting it is only
half of this requirement; a script that cannot read it is the other half, and
an arrival check written against an unreadable field is the re-issuing-forever
shape of trial 4.3.

A distance-teleport (`GotoBehavior.java:175`, beyond `TELEPORT_THRESHOLD`)
MUST use the same bounded, reported target. It reads `targetY`, which `start`
sets to the bounded lift result, so a far target can no longer be teleported to
a lifted surface position.

#### Scenario: Trial 4.2's enclosed target fails instead of climbing
- **GIVEN** a script that dispatches `GOTO x=-123 y=-44 z=-152`, whose target
  block is enclosed in stone
- **WHEN** no clear standing position exists within `GOTO_MAX_LIFT` blocks above
- **THEN** the directive MUST fail with reason `target_enclosed`
- **AND** the failure MUST name `(-123, -44, -152)`
- **AND** the bot MUST NOT move to or near `y = -8`

#### Scenario: A target under a shallow ledge is still lifted and reported
- **GIVEN** a `GOTO` whose target is covered by one block of stone
- **WHEN** the block above is clear
- **THEN** the directive MUST proceed to the lifted position
- **AND** on arrival the COMPLETED result MUST carry the actual position and an
  `adjusted_from` naming the original coordinates

#### Scenario: An unreachable enclosed target is not teleported to
- **GIVEN** an enclosed `GOTO` target further away than `TELEPORT_THRESHOLD`
- **WHEN** the lift would need to exceed `GOTO_MAX_LIFT`
- **THEN** the directive MUST fail rather than teleport to the lifted `targetY`

#### Scenario: The script surface warns against targeting a block itself
- **GIVEN** the rendered script prompt
- **WHEN** a planner reads it
- **THEN** it MUST say that to work on a block, GOTO a neighbouring open block
  or a position within reach, not the block itself
- **AND** it MUST NOT suggest that GOTO into a solid block is adjusted for the
  caller

### Requirement: A Stop Or Reset Cancels The Work That Would Outlive It

A stop and a reset MUST beat a re-plan that is already in flight, not only the
one running when the player typed. Both terminal transitions MUST cancel work
that was already on its way to re-binding the goal they ended, and a plan that
completes after one of them MUST NOT bind a script or set a plan for the
stopped goal.

The failure this requirement exists to stop: on 2026-11-22 at 07:01:40Z a
player sent `stop` while a script had yielded its goal and the agent was
re-planning it. The log order was the abort, then the nav stop, and only then
`[script] bound (planner, in memory) (0b62fe044f914f1b)` -- a script bound to a
goal the player had just stopped. The stopped goal then re-planned again and
bound a second one (`7df52ecc6ec16e7a`), and the loop continued until the
re-plan bound stopped it. Those scripts dispatched nothing; a mining or
walking script would have acted after the stop.

`_cancel_orchestrator` alone cannot close this. It signals the orchestrator run
that is executing NOW, and a re-plan started after the stop is a new run that
never observes an event set before it began. The cancellation therefore MUST
carry something that outlives a single run:

- A stop and a reset MUST each advance a generation counter.
- A re-plan or plan run MUST capture the generation it was started under and
  MUST refuse to bind a script or set a plan once that generation is stale.
- The yield re-plan MUST NOT start for a goal that was stopped or reset: the
  check MUST be on the path that re-submits the goal, so a running
  orchestrator that finishes after the stop cannot create it either.

The refusal MUST be logged, naming the goal and the fact that a stop or reset
superseded it, so a later log read can tell "nothing happened" from "something
was correctly stopped".

#### Scenario: A stop during an in-flight yield re-plan binds nothing
- **GIVEN** a planner-authored script that yielded its goal G
- **AND** a re-plan of G is running
- **WHEN** the player sends exactly `stop`
- **THEN** no script MUST bind afterwards for G
- **AND** no further re-plan of G MUST start
- **AND** the refusal MUST be logged with G's id

#### Scenario: A reset during an in-flight yield re-plan binds nothing
- **GIVEN** a planner-authored script that yielded its goal G
- **AND** a re-plan of G is running
- **WHEN** the bot is reset
- **THEN** no script MUST bind afterwards for G
- **AND** no further re-plan of G MUST start

#### Scenario: A new goal after a stop is unaffected
- **GIVEN** a stop superseded goal G while a re-plan of G was in flight
- **WHEN** the player gives a new goal H
- **THEN** H MUST be planned normally
- **AND** H MUST be able to bind a planner script

### Requirement: A Planner Script Is Unbound When Its Work Ends Without Succeeding

A planner-authored script MUST NOT outlive the work it was written for. Three
transitions end that work, and each MUST leave the bot in a state where the
script is no longer ticking:

1. The goal closes `done` -- already true, and before this change the only
   case that unbound was the `_unbind_planner_script()` call at the `done`
   close, just after `_complete_task_board_task`.
2. A failure result is handed back to the planner. The script reported that it
   could not do the job; the planner is choosing another approach, so the old
   script is not the thing to keep running. Left bound, it
   pays a runner call every tick and can suppress its own `say` indefinitely.
3. The player sends a stop. A player's "stop" MUST stop a script that mines or
   walks, not only the planner that wrote it.
4. The bot is reset. A reset is terminal in the same way a stop is: it clears
   the plan, the goal and the script hold, so a bound planner script left alone
   would resume ticking with no goal and no plan to serve. `reset()` MUST treat
   a script exactly as a stop does. Without this it is the one terminal path
   that still leaves the planner's script running, which is the same defect
   this requirement closes for (2) and (3).

For (2), (3) and (4) the unbind MUST be `_unbind_planner_script` itself, not a
second mechanism that clears the same fields. That function already refuses to
touch a hand-written script (`_planner_script` is empty for one), so the
"deployment-bound scripts are not unbound" half is structural rather than a
condition someone must remember to check -- which is the property that makes
it safe to call from a path that does not know which kind it has.

A stop is NOT a hold. `_script_hold` is a pause owned by a goal and cleared
when that goal ends; a stop ends the work, so reusing the hold would leave a
halted script waiting for a release that never comes. The two MUST be separate
states, and the log MUST say which one happened.

#### Scenario: A failed hand-back unbinds the planner's script
- **GIVEN** a planner-authored script bound to goal G
- **AND** a tick whose result the planner receives as a failure
- **WHEN** the hand-back path starts the planner
- **THEN** the planner's script MUST be unbound
- **AND** the next tick MUST NOT call the runner for it
- **AND** the goal MUST remain open, so the planner answers it

#### Scenario: A failed hand-back leaves a hand-written script bound
- **GIVEN** a script bound from `bindings.json` for this bot
- **AND** a tick whose result is handed back to the planner as a failure
- **WHEN** the hand-back runs
- **THEN** the hand-written script MUST still be bound
- **AND** it MUST keep ticking

#### Scenario: A stop unbinds the planner's script
- **GIVEN** a planner-authored script bound and ticking
- **WHEN** the player sends exactly `stop`
- **THEN** the script MUST be unbound
- **AND** a subsequent tick MUST NOT call the runner
- **AND** the stop MUST still cancel the orchestrator and the directive, as it
  does today

#### Scenario: A stop halts a hand-written script for the stop period
- **GIVEN** a script bound from `bindings.json` for this bot
- **WHEN** the player sends exactly `stop`
- **THEN** the script MUST NOT dispatch a further action while the bot is
  stopped
- **AND** it MUST remain bound, so the player's deployment is not erased
- **AND** the next goal the bot accepts MUST let it dispatch again

#### Scenario: A reset unbinds the planner's script
- **GIVEN** a planner-authored script bound and ticking
- **WHEN** the bot is reset (`reset()`, the in-game "All tasks cleared")
- **THEN** the script MUST be unbound
- **AND** a subsequent tick MUST NOT call the runner
- **AND** the reset MUST still cancel the orchestrator and the directive, as it
  does today

#### Scenario: A reset halts a hand-written script and keeps it bound
- **GIVEN** a script bound from `bindings.json` for this bot
- **WHEN** the bot is reset
- **THEN** the script MUST NOT dispatch a further action while the bot is
  stopped
- **AND** it MUST remain bound, so the player's deployment is not erased
- **AND** the next goal the bot accepts MUST let it dispatch again

### Requirement: The Script Surface Is Offered Per Bot, Not Per Deployment

Scripts MUST be offered to a bot's planner only when that bot is BOTH enabled
for scripts AND has a runner configured. Today `render_planner_prompt`
substitutes `SCRIPT_SURFACE` unconditionally, so every bot in every deployment
is offered scripts -- including prod, which has no runner at all. There, all
five bots could write scripts that fail at tick for want of a runner and fall
back, spending planner calls to learn something the prompt should never have
offered.

The enabled set MUST come from deployment config, never from a default:

- `SCRIPT_BOTS` is a comma-separated list of bot names, matched case-
  insensitively and stripped of surrounding whitespace.
- Empty or unset `SCRIPT_BOTS` means NO bot is enabled. The default MUST be
  none: a deployment that has not opted in must not silently start offering
  scripts, which is how prod would reach the state this requirement exists to
  prevent.
- A bot is offered scripts only if it is named in `SCRIPT_BOTS` AND a runner
  (`SCRIPT_RUNNER_URL`) is configured. Naming a bot while the runner is unset
  MUST NOT offer scripts -- there is nothing for a script to run on.

A bot that is not offered the surface gets the planner prompt WITHOUT the
script section, and any `script` field it returns anyway MUST be ignored with
one log line naming the bot and saying why. Ignoring is not an error: the
prompt no longer asks for a script, so a stray field is noise, and failing the
plan for it would punish the model for a field the prompt stopped requesting.

`SCRIPT_SURFACE` is spliced into both the planner prompt and the L3 script
prompt, so the two MUST stay in step: whichever gate decides for one decides
for the other, and a change that gates one but not the other is a defect even
though each alone looks right.

At startup the agent MUST log, per bot, whether script mode is on or off and
why -- enabled-and-runner-configured, not in `SCRIPT_BOTS`, or no runner. This
is the only way a deployment can see from its logs that the switch took effect
without reading its own manifests back.

#### Scenario: An enabled bot with a runner is offered the surface
- **GIVEN** `SCRIPT_BOTS` names this bot
- **AND** `SCRIPT_RUNNER_URL` is set
- **WHEN** the planner prompt is rendered
- **THEN** it MUST contain the script surface
- **AND** the startup log MUST say script mode is on and why

#### Scenario: A bot not named is offered nothing
- **GIVEN** `SCRIPT_BOTS` names some other bot
- **WHEN** this bot's planner prompt is rendered
- **THEN** it MUST NOT contain the script surface
- **AND** a `script` field returned anyway MUST be ignored with one log line
- **AND** the goal MUST proceed on the plan's steps rather than failing

#### Scenario: No runner means no bot is offered scripts
- **GIVEN** `SCRIPT_BOTS` names this bot
- **AND** `SCRIPT_RUNNER_URL` is unset
- **WHEN** the planner prompt is rendered
- **THEN** it MUST NOT contain the script surface
- **AND** the startup log MUST say script mode is off because there is no runner

#### Scenario: An unset enabled set offers nothing
- **GIVEN** `SCRIPT_BOTS` is unset or empty
- **AND** a runner is configured
- **WHEN** any bot's planner prompt is rendered
- **THEN** it MUST NOT contain the script surface
- **AND** the startup log MUST say script mode is off and name the bot as not
  enabled

### Requirement: The Plan Prompt Must Not Invite A Script A Bot Is Not Offered

A bot that is not offered the script surface MUST NOT be taught how to ask for
one. Withholding the surface inside a call that still happens does not save the
call: the L3 plan prompt (`_PLAN_SYSTEM_PROMPT`) both explains "Choose between a
STEP LIST and a SCRIPT" and instructs the model to set `"wants_script": true`,
and `call_plan` fires `call_script` whenever that flag is set, with no gate of
its own. A bot outside `SCRIPT_BOTS` therefore reads an invitation, accepts it,
and spends a second planner call to be handed a script prompt with the entire
surface blanked -- the same wasted call this group of requirements exists to
remove, arriving one layer above where the previous gate looks.

The invitation and the capability MUST agree. When a bot is not offered the
surface, the script section of the plan prompt -- the "Choose between a STEP
LIST and a SCRIPT" teaching, the example surface, and the `wants_script` flag --
MUST be absent, so the model is never told to ask for what the deployment cannot
honour. `call_plan` MUST ALSO decline to fetch a script for a bot that is not
offered one, because a plan prompt is not a contract: a model that sets the flag
from habit or from a stale cached prompt MUST NOT cost a second call. Both
halves are required; either alone leaves the invitation and the capability able
to disagree.

Declining to fetch is not an error: the goal MUST proceed on the plan's steps,
exactly as a stray `script` field is ignored rather than failed.

#### Scenario: The plan prompt of a non-enabled bot invites no script
- **GIVEN** `SCRIPT_BOTS` names some other bot
- **WHEN** this bot's plan prompt is rendered
- **THEN** it MUST NOT teach `wants_script`
- **AND** it MUST NOT contain the script API surface
- **AND** the instruction to choose between a step list and a script MUST be
  absent

#### Scenario: A non-enabled bot that asks anyway costs no second call
- **GIVEN** `SCRIPT_BOTS` does not name this bot
- **AND** the plan reply carries `"wants_script": true`
- **WHEN** `call_plan` processes that reply
- **THEN** it MUST NOT make the second, script-writing call
- **AND** the goal MUST proceed on the plan's steps rather than failing
- **AND** it MUST log one line naming the bot and saying why no script was
  fetched

#### Scenario: An enabled bot with a runner keeps both halves
- **GIVEN** `SCRIPT_BOTS` names this bot
- **AND** `SCRIPT_RUNNER_URL` is set
- **WHEN** its plan prompt is rendered and the reply sets `wants_script`
- **THEN** the prompt MUST teach `wants_script` and contain the surface
- **AND** `call_plan` MUST make the second, script-writing call

### Requirement: A Rebuilt Prompt Must Recover Whether Scripts Were Offered

The eval harness rebuilds a recorded plan prompt to score a candidate against
it, and the section is per bot, so the bot's name does not say whether the
recorded call offered scripts. The recorded prompt is the only place that says.
Recovery MUST therefore distinguish three cases rather than two: the section is
present and matches this build (recovers verbatim); the section was never sent
(rebuilds to empty, which is what that call sent); and the prompt carries the
section heading but not this build's text, meaning another build offered scripts
with wording this one does not hold.

The third case MUST be reported unscorable, not rebuilt as empty. An empty
section sends the candidate a prompt the model never saw and compares it to one
that carried the surface -- a plausible substitution, which this harness treats
as a lie everywhere else it can distinguish the cases.

#### Scenario: A recorded offer is recovered verbatim
- **GIVEN** a recorded plan prompt carrying this build's script section
- **WHEN** the prompt is rebuilt
- **THEN** the rebuilt prompt MUST contain that section unchanged

#### Scenario: A recorded absence rebuilds to empty
- **GIVEN** a recorded plan prompt with no script section
- **WHEN** the prompt is rebuilt
- **THEN** the rebuilt prompt MUST contain no script section

#### Scenario: Another build's section makes the case unscorable
- **GIVEN** a recorded plan prompt carrying the script heading with text this
  build does not hold
- **WHEN** the prompt is rebuilt
- **THEN** the case MUST be reported unscorable rather than rebuilt as empty
- **AND** the reason MUST say the recorded prompt offered scripts

### Requirement: The Script Surface Needs The L3 Path, And `SCRIPT_BOTS` Opts A Bot Into It

The script surface is spliced into the L3 plan prompt only, so a bot whose chat
reaches the legacy `decompose` path can never write a script. Prod proves the
gap rather than the theory: its agent config has no `USE_L3_PLAN_LAYER`,
`config.py` defaults the flag to false, and prod therefore plans every chat
through `decompose` -- which makes every script requirement above unreachable
on prod no matter what `SCRIPT_BOTS` says.

`USE_L3_PLAN_LAYER` is asked once per deployment and read at three separate
call sites (chat gating, L3 acceptance, and the order lane), so flipping it
moves every bot in the deployment at once. That is the wrong granularity twice
over: prod cannot enable scripts for one bot without re-planning all five, and
`SCRIPT_BOTS` -- which already names the bots that may script -- has no say in
whether those bots can reach the path their scripts run on.

Routing MUST therefore be decided per bot by a single predicate used at all
three sites, never by the flag alone and never by three copies that can drift:

- The predicate is true when `USE_L3_PLAN_LAYER` is true, OR when this bot is
  named in `SCRIPT_BOTS`. Deployment-level enablement stays a fleet-wide switch;
  naming a bot adds that bot to the L3 path without moving any other bot.
- A bot not named in `SCRIPT_BOTS` MUST behave exactly as it does today for
  whichever value the flag holds. With the flag unset it plans through
  `decompose`; with the flag true it uses L3, unchanged.
- Naming a bot MUST NOT, by itself, offer it the script surface. Reachability
  and offering stay separate: a bot in `SCRIPT_BOTS` with no
  `SCRIPT_RUNNER_URL` reaches L3 and gets the plan prompt WITHOUT the script
  section. That composition is the point -- the path is necessary and not
  sufficient.

Because all three sites must agree, the predicate MUST be one function rather
than three conditions. A change that routes chat to L3 while the order lane
still refuses, or vice versa, leaves a bot that accepts a goal it cannot order,
which is a defect even though each site alone looks correct.

#### Scenario: Flag unset and the bot is listed
- **GIVEN** `USE_L3_PLAN_LAYER` is unset or false
- **AND** `SCRIPT_BOTS` names this bot
- **WHEN** the bot is handed an instruction
- **THEN** it MUST take the L3 path, and MUST NOT fall through to `decompose`
- **AND** this MUST hold at the chat gate, the acceptance check and the order
  lane alike

#### Scenario: Flag unset and the bot is not listed
- **GIVEN** `USE_L3_PLAN_LAYER` is unset or false
- **AND** `SCRIPT_BOTS` names some other bot, or is unset
- **WHEN** this bot is handed an instruction
- **THEN** it MUST plan through `decompose`, exactly as today
- **AND** the order lane MUST still report the L3 layer as disabled for it

#### Scenario: Flag true and the bot is not listed
- **GIVEN** `USE_L3_PLAN_LAYER` is true
- **AND** `SCRIPT_BOTS` does not name this bot
- **WHEN** this bot's plan prompt is rendered
- **THEN** the bot MUST still take the L3 path, because the deployment asked
  for it
- **AND** the prompt MUST NOT contain the script section, because a bot not in
  `SCRIPT_BOTS` is never offered scripts

#### Scenario: Listing a bot without a runner moves no other bot and offers no script
- **GIVEN** `USE_L3_PLAN_LAYER` is unset
- **AND** `SCRIPT_BOTS` names this bot
- **AND** `SCRIPT_RUNNER_URL` is unset
- **WHEN** the deployment starts
- **THEN** this bot MUST reach the L3 path
- **AND** its plan prompt MUST NOT contain the script section
- **AND** no bot outside `SCRIPT_BOTS` MUST change its routing

#### Scenario: One predicate, three sites
- **GIVEN** any combination of the flag and `SCRIPT_BOTS`
- **WHEN** the chat gate, the acceptance check and the order lane each decide
- **THEN** all three MUST return the same answer for the same bot
- **AND** a test that overrides only one site's condition MUST fail this
  scenario

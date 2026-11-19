# AI-written bot scripts — the planner authors the script (M3-2 step a)

## Why

The owner (Slack 11-19 19:05Z): adopt programmatic tool calling for the bots,
in order (a) the planner LLM writes the bot's JS script, (b) read-only lookup
functions in the script sandbox, (c) the script result returned to the planner.
**This change is step (a), spec only.** No code until the spec is approved.

## What already exists (checked, not assumed)

Most of "the LLM writes the script" is **already specified** — and only
specified, not built: none of it is in `openspec/specs/` yet and the code does
not exist. It lives in the open change `openspec/changes/coded-agents/`. That
change already has:

- **"Script Authoring Is LLM-Only"** — only the LLM may create or modify a
  script; players may read, not write.
- **"Authoring Rejects Code That Cannot Run"** — a proposal is validated
  (syntax, action names, filesystem/network) before store; a failed attempt is
  discarded and the previous script stays in force.
- **"Script Execution Is Sandboxed And Tick-Bounded"**, **"The Script API Is
  The Minecraft Binding"** (six `api.*` methods), the **Runner Contract v1**
  limits table, and **"The Existing Planner Remains Available As A Fallback"**.
- **"A Player Goal Yields A Running Script"** — the M3-1g rule: a chat command
  holds a running script; the script resumes with its remembered value.

This change does **not** re-specify any of that. Re-stating a live requirement
in a second change is how two specs come to disagree.

## What Changes

- **Add** the planner as a producer of scripts: while planning a world goal, the
  L3 planner MAY emit a script as the plan, not only a directive list.
- **Add** a dry-tick gate before binding: a planner-authored script runs once
  against the bot's snapshot with actions suppressed, and is bound only if that
  tick returns `ok`.
- **Add** a stated rule for when a written script is used versus the plain
  planner, decided by conditions rather than by the model's preference.
- **Not change**: the skill layer's "no arbitrary executable" rule, the
  six-method `api` surface, the runner's limits, the mod's Java skill engine,
  the M3-1g hold, or hand-written scripts.

## The three real gaps for step (a)

The owner's framing — the *planner* writes the script *for a goal*, as a
programmatic alternative to emitting directives — exposes three things the
existing change does not say. Each is the subject of one ADDED requirement.

1. **The planner authors a script during planning.**
   Today script source is a separate artefact (hand-written, or produced by an
   out-of-band author). Nothing says the L3 planner, while planning a goal, may
   emit a script *as the plan* instead of a list of directives. Step (a) is
   exactly that: a planning outcome of kind "here is a script for this goal".

2. **A dry tick before binding — and binding is a REBIND.**
   "Authoring Rejects Code That Cannot Run" requires the proposal to *parse* and
   pass name/fs/network checks before it is **stored**. That is necessary and
   not sufficient for *binding to a live bot*: a script can be syntactically
   valid and still fail on its first real tick (throws immediately, exceeds the
   per-tick host-call budget, loops past the CPU budget). The missing gate is a
   **dry tick**: run the script once against the bot's current snapshot with
   actions suppressed, and bind it only if that tick returns `ok`. A failed dry
   tick is a fallback to the plain planner, never a stored-and-broken script.

   **The word "bind" hides a mechanism that does not exist yet.** A bot resolves
   its script once for the process lifetime: `_script_loaded` is `False` at
   `agent/agent.py:235`, returns the cached tick at `:3052` and is set `True`
   at `:3054`, with one production caller at `:2890`. Binding is therefore a
   **rebind**, and the spec says so explicitly: the latch gains a defined reset
   for a planner-authored script, and that reset is its only writer. An
   implementer who calls the existing path without it gets the previous script
   forever.

   **The dry tick is not free, and "actions suppressed" understates it.**
   Discarding actions costs nothing — `api.do` pushes onto a sandbox-local array
   (`binding.js:244-251`). But `acceptAction` records every accepted call in
   `botState.actionTimes` (`binding.js:154-174`), per-BOT state that
   deliberately survives a tick (`binding.js:45-52`), against budgets of
   `do:30/min`, `say:30/min`, `send:20/min` (`:44`). A dry tick that spends up
   to 8 `do` slots for a script it then rejects takes those slots from the
   bot's real work. Memory is the mirror case: `api.remember` writes per-tick
   state (`binding.js:314`), so the sandbox discards it — but
   `script_tick.py:364` adopts the returned memory, so the dry tick must not.
   Both are named in the requirement so they are testable; neither needs an
   engine change.

3. **When the agent uses a written script vs the plain planner.**
   No requirement decides this. "A Player Goal Yields A Running Script" is about
   chat *pausing a running* script; it does not say when the planner *chooses*
   to script at all. Without a rule, the choice is the model's whim.

   The rule is stated as conditions, and the condition is **per BOT**: binding
   is `bindings.get(self.name)` (`agent.py:3027`), with no goal-to-script
   association anywhere, so a per-goal condition would be vacuously satisfiable
   and would pretend to an association the code does not have.

   The condition is specifically "no **hand-written** script is bound", not "no
   script is bound". Two things force that. First, `bindings.json` is a flat
   bot-name-to-filename map (`{"Scout": "scout.js"}`) with no provenance field,
   so hand-written cannot be read off it — the agent must record in process
   which script it bound itself, and condition 2 then asks whether *it* put the
   bound script there or a human did. Second, and decisively: gating on any
   bound script would make the B1 latch reset unreachable in the only case it
   exists for, a bot already running a working script. A hand-written script is
   a deliberate deployment and a planner must not silently overwrite it; a
   previously written script is the agent's own prior output and displacing it
   is the point of step (a).

## The design tension this change names, and does not hide

The skill layer draws a deliberate boundary
(`openspec/specs/skill-layer/spec.md`): a skill is "a JSON spec the mod
validates… It MUST NOT be Java code or any arbitrary executable." AI-written
scripts are **arbitrary executable authored by a model** — the class that
boundary excludes. This change does not blur the two: a skill stays validated
JSON; a script stays a sandboxed program. The safety argument rests on the
sandbox being real and measured, copied from the runner rather than assumed:

- `agent-script-runner/src/engine.js:2-12` — one QuickJS-WASM runtime per bot;
  "No filesystem and no network. Measured, not assumed."
- `agent-script-runner/src/main.js:51` — `MAX_SOURCE_BYTES = 64 * 1024`.
- `agent-script-runner/src/engine.js:32,41` — stack 256 KiB, heap 32 MiB.
- `agent-script-runner/src/binding.js:31` — "more than 8 accepted host calls in
  one tick is `host_calls_exceeded`."
- `agent-script-runner/src/binding.js:225-318` — the `api` object: exactly six
  methods (`do`, `say`, `send`, `recall`, `remember`, `log`).

A script reaches the world only through `api.do`, at most 8 host calls a tick,
inside 64 KiB, with no filesystem and no network. That is the boundary the new
requirements lean on.

## What stays (must not regress)

- The skill layer's "declarative data, not arbitrary executable" rule.
- The six-function `api` surface — not added to, removed, or renamed here.
  (Step (b)'s read-only lookups are a later, separate change.)
- The M3-1g hold: an AI-written script is held exactly like a hand-written one.
- Hand-written and out-of-band-authored scripts keep working unchanged.
- The fallback: any failure of the written script path lands the bot on the
  plain planner, never idle and never unsafe.

## Scope

Specification only: behaviour, the dry-tick gate, and the use-vs-plain-planner
rule. It does not implement the writer, the dry-tick harness, or the bind
decision; it does not touch the mod's Java skill engine, the runner's limits, or
steps (b)/(c). No code until the lead approves the spec. Nothing pushed,
nothing deployed.

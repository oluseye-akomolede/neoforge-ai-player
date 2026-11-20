# Tasks — AI-written bot scripts (M3-2 step a)

Spec only. No code, no build, no deploy until the lead approves this spec.

## 1. Settle the spec (this change)

- [x] 1.1 Establish what already exists: `coded-agents` (an unarchived change,
      nothing in `openspec/specs/`, no code) already specifies LLM-only
      authoring, validate-before-store, the sandbox, the six-method API,
      Runner Contract v1 limits, the plain-planner fallback, and the M3-1g hold.
      This change re-states none of it.
- [x] 1.2 Name the three genuine gaps step (a) exposes: (i) the planner MAY emit
      a script as the plan for a goal; (ii) a **dry tick** before binding, not
      only a parse check; (iii) a stated rule for script vs plain planner.
      Each is one ADDED requirement in `specs/bot-coded-agents/spec.md`.
- [x] 1.3 Write the proposal, the delta and these tasks. No code.
- [ ] 1.4 Validate: `openspec validate ai-written-scripts --strict`.
- [ ] 1.5 Reviewer pass on the delta. Findings are spec findings until the lead
      rules otherwise.

## 2. Recorded design decisions (so a later implementer does not guess)

- [ ] 2.1 The skill layer keeps its rule: a skill is validated JSON, never an
      executable (`openspec/specs/skill-layer/spec.md`). A script is a
      sandboxed program. This change does not merge them.
- [ ] 2.2 The safety case is the sandbox, stated with its real limits and not
      assumed: QuickJS-WASM, one runtime per bot, no filesystem, no network
      (`agent-script-runner/src/engine.js:2-12`); `MAX_SOURCE_BYTES = 64 * 1024`
      (`main.js:51`); stack 256 KiB, heap 32 MiB (`engine.js:32,41`); at most 8
      accepted host calls per tick, else `host_calls_exceeded`
      (`binding.js:31`); the six `api` methods only (`binding.js:225-318`).
- [ ] 2.3 A dry tick runs once against the bot's snapshot with actions
      **suppressed** (queued, discarded, not dispatched). It binds only on
      `ok`. A failed dry tick falls back to the plain planner and keeps any
      previously bound script in force.
- [ ] 2.4 **Binding is a rebind.** `_script_loaded` is a one-shot latch
      (`agent/agent.py:235,3138-3140`; one production caller at `:2890`), so a
      bot resolves its script once for the process lifetime. The latch gains a
      defined reset for a planner-authored script, and that reset is its ONLY
      writer. Without it, calling the existing path returns the previous
      script forever.
- [ ] 2.5 **A dry tick spends no rate budget and carries no memory.**
      `acceptAction` records calls in `botState.actionTimes`
      (`binding.js:154-174`), per-BOT state that survives a tick
      (`binding.js:45-52`) against `do:30/min`, `say:30/min`, `send:20/min`
      (`:44`); the dry tick must leave `actionTimes` unchanged.
      `api.remember` writes per-tick `state.memoryOut` (`binding.js:314`) so
      the sandbox discards it, but `script_tick.py:387` adopts the returned
      memory — the dry tick's memory must be discarded too.
- [ ] 2.6 The decision "script vs plain planner" is conditions, not model
      preference: (1) planning kind allows scripting; (2) no HAND-WRITTEN
      script is currently bound to this bot; (3) dry tick passed. Any failure
      → plain planner. Condition 2 is per BOT because
      `bindings.get(self.name)` (`agent.py:3113`) is per bot and no
      goal-to-script association exists; it does not contradict the M3-1g
      hold, which names the goal that owns a pause, not the script a goal
      owns.
- [ ] 2.7 **"Hand-written" is read from `bindings.json`, which now names only
      hand-written scripts.** A planner-authored script is carried in memory
      and is never added to `bindings.json`, so an entry there can only have
      been placed by a human. Condition 2 asks "does `bindings.json` name a
      script for this bot?". A yes is a deliberate human deployment a planner
      must not overwrite; a no leaves the bot free for a written script. This
      keeps the 2.4 latch reset reachable for the agent's own previous script,
      which leaves no file entry.
- [ ] 2.8 **The script lives in memory, so a restart DROPS it rather than
      freezing it.** The agent has NO write path for script source:
      `scripts_dir` comes from `SCRIPTS_DIR` (`agent.py:3092`) and the only
      accesses are reading `bindings.json` (`:3097`) and joining the filename
      (`:3121`). The emitted script is therefore passed straight to the runner
      as the tick's source. Consequence: on restart the in-memory script is
      gone and the bot falls back to its `bindings.json` script or the plain
      planner — no error, no missed tick, and NOT silently resumed.
      This REPLACES the earlier "a bot cannot replace its own pre-restart
      script until a human unbinds it" cost. Do NOT add a write path or a
      `bindings.json` provenance field: in-memory is the design, and no new
      storage is in scope.

## 3. What is deliberately out of scope

- [ ] 3.1 Step (b): read-only lookup functions inside the sandbox. Later change.
- [ ] 3.2 Step (c): the script's result returned to the planner. Later change.
- [ ] 3.3 No change to the six-function `api` surface, the runner's limits, or
      the mod's Java skill engine.
- [ ] 3.4 Implementation follows this spec: the planner's script output kind and
      prompt, the agent's dry-tick call, the rebind latch reset and the three
      conditions. Test-first, reviewed before any deploy to test.

## 4. Known precondition, recorded not acted on

- [ ] 4.1 The `coded-agents` change is unarchived. When it eventually ships to
      prod it will be archived into `openspec/specs/`, and this change's delta
      then becomes a MODIFIED delta on the live `bot-coded-agents` capability,
      not an ADDED one. This change is written to be additive either way.

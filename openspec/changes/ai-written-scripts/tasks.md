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
- [ ] 2.4 The decision "script vs plain planner" is conditions, not model
      preference: (1) planning kind allows scripting; (2) dry tick passed;
      (3) no script already driving this goal. Any failure → plain planner.

## 3. What is deliberately out of scope

- [ ] 3.1 Step (b): read-only lookup functions inside the sandbox. Later change.
- [ ] 3.2 Step (c): the script's result returned to the planner. Later change.
- [ ] 3.3 No change to the six-function `api` surface, the runner's limits, or
      the mod's Java skill engine.
- [ ] 3.4 No code in this change. The writer, the dry-tick harness and the bind
      decision are a later implementation change, planned from this spec.

## 4. Known precondition, recorded not acted on

- [ ] 4.1 The `coded-agents` change is unarchived. When it eventually ships to
      prod it will be archived into `openspec/specs/`, and this change's delta
      then becomes a MODIFIED delta on the live `bot-coded-agents` capability,
      not an ADDED one. This change is written to be additive either way.

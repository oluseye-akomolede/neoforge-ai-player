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
- [x] 1.4 Validate: `openspec validate ai-written-scripts --strict`.
      (rc=0, 2026-11-22, after the three PTC prod deltas below.)
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
- [x] 2.3 A dry tick runs once against the bot's snapshot with actions
      **suppressed** (queued, discarded, not dispatched). It binds only on
      `ok`. A failed dry tick falls back to the plain planner and keeps any
      previously bound script in force.
- [x] 2.4 **Binding is a rebind.** `_script_loaded` is a one-shot latch
      (`agent/agent.py:235,3213-3215`; one production caller at `:2916`), so a
      bot resolves its script once for the process lifetime. The latch gains a
      defined reset for a planner-authored script, and that reset is its ONLY
      writer. Without it, calling the existing path returns the previous
      script forever.
- [x] 2.5 **A dry tick spends no rate budget and carries no memory.**
      `acceptAction` records calls in `botState.actionTimes`
      (`binding.js:154-174`), per-BOT state that survives a tick
      (`binding.js:45-52`) against `do:30/min`, `say:30/min`, `send:20/min`
      (`:44`); the dry tick must leave `actionTimes` unchanged.
      `api.remember` writes per-tick `state.memoryOut` (`binding.js:314`) so
      the sandbox discards it, but `script_tick.py:387` adopts the returned
      memory — the dry tick's memory must be discarded too.
- [x] 2.6 The decision "script vs plain planner" is conditions, not model
      preference: (1) planning kind allows scripting; (2) no HAND-WRITTEN
      script is currently bound to this bot; (3) dry tick passed. Any failure
      → plain planner. Condition 2 is per BOT because
      `bindings.get(self.name)` (`agent.py:3139`) is per bot and no
      goal-to-script association exists; it does not contradict the M3-1g
      hold, which names the goal that owns a pause, not the script a goal
      owns.
- [x] 2.7 **"Hand-written" is read from `bindings.json`, which now names only
      hand-written scripts.** A planner-authored script is carried in memory
      and is never added to `bindings.json`, so an entry there can only have
      been placed by a human. Condition 2 asks "does `bindings.json` name a
      script for this bot?". A yes is a deliberate human deployment a planner
      must not overwrite; a no leaves the bot free for a written script. This
      keeps the 2.4 latch reset reachable for the agent's own previous script,
      which leaves no file entry.
- [x] 2.8 **The script lives in memory, so a restart DROPS it rather than
      freezing it.** The agent has NO write path for script source:
      `scripts_dir` comes from `SCRIPTS_DIR` (`agent.py:3118`) and the only
      accesses are reading `bindings.json` (`:3123`) and joining the filename
      (`:3147`). The emitted script is therefore passed straight to the runner
      as the tick's source. Consequence: on restart the in-memory script is
      gone and the bot falls back to its `bindings.json` script or the plain
      planner — no error, no missed tick, and NOT silently resumed.
      This REPLACES the earlier "a bot cannot replace its own pre-restart
      script until a human unbinds it" cost. Do NOT add a write path or a
      `bindings.json` provenance field: in-memory is the design, and no new
      storage is in scope.

## 2a. Sub-step a2 — reach the path a goal actually runs on

The step (a) work above was wired into `planner.decompose`, and deployed. It was
inert for real goals: a player goal is planned by `plan_orchestrator.execute_task`
→ `l3_planner.call_plan`, and three hours of test logs showed `L3 PLAN`/`L3 EXEC`
with zero decompose calls. The lead ruled (A): move the script output onto the
L3 path rather than limit the spec to the decompose paths.

- [x] 2a.1 **The script is ONE extra optional part of `call_plan`'s reply,
      fetched in its own call** — not a new `kind`, not a new directive type,
      and not a key of any JSON object the trainer sees. The plan call keeps
      JSON mode and its reply shape, gaining one optional `wants_script`
      boolean; only when it is true does `call_script` make a second, non-JSON
      call whose whole reply is a fenced ```js block. `extract_script_block`
      reads it and `Plan` carries it in memory for dispatch; `Plan.to_dict()`
      needs no exclusion, because the script was never in the dict at all.
      A JSON key is not a channel: on test at 2026-11-20 15:57Z one raw newline
      inside the JSON string made `json.loads` fail and took the plan with it.
- [x] 2a.2 **No script means byte-identical today.** With `wants_script` false
      or absent, exactly one planner call is made, in the same JSON mode with
      the same reply shape, and the record `trajectory_log.log_call` writes is
      unchanged apart from that one field. Pinned by tests that assert the
      call count is 1, that the plan call still sends `format: "json"`, and that
      the logged `response_raw` equals the reply verbatim.
- [x] 2a.3 **The script is kept out of every field the trainer reads, not just
      `parsed`.** `build_dpo_dataset.py:89-93` builds `chosen`/`rejected` from
      `response_raw` verbatim, so a `parsed`-only guard leaves the leak in the
      trained field. The DPO export may read `call_plan` prompts and replies
      (asked of dags-lead, row `qitem-20261120145614-65eb3af3994b0a26`);
      until they answer, no field `build_dpo_dataset.py` reads may contain
      script source. Pinned by a test asserting `response_raw` and `parsed` are
      both script-free for a script-carrying reply.
- [x] 2a.4 **The orchestrator binds it.** `execute_task` hands the script to the
      caller through the existing `on_plan_created` hook, or an equivalent one
      argument; the agent's hook calls `_bind_planner_script`, which already
      holds the three orderings (hand-written wins, dry tick before assignment,
      latch reset). Shipped as a separate `on_script` argument rather than
      reusing `on_plan_created`: the hook must return whether it accepted the
      goal, and `on_plan_created` fires on every plan, script or not.
- [x] 2a.5 **Hand-written bindings still win** — unchanged rule, now reachable
      from the goal path.
- [x] 2a.6 **Binding a goal's own script RELEASES that goal's hold.** The
      M3-1g hold covers a script already bound when the goal arrived. A script
      the planner writes FOR that goal is the goal's own execution, so holding
      it would suppress the one run the goal asked for — and for a repeating
      goal nothing would happen until some unrelated path ended it. Release
      through the existing identity-guarded `_end_script_hold(goal_id)`, as
      part of the bind and not as a separate step, so there is no bound-but-held
      window and a newer goal's hold is never released by an older bind. Note
      the current docstring of `_begin_script_hold` argues the opposite for the
      cancel case; that reasoning is about cancellation, not about this
      release, and the delta is the record of the difference. Test both
      directions and the order: pre-existing script stays held, goal's own
      script binds then dispatches, and a non-matching goal_id releases
      nothing.
- [x] 2a.7 **Which paths author scripts is stated, and matches the code.**
      Orchestrator: yes. Decompose: yes, kept and reachable. Plan-template and
      plan-memory hits: no (Phase 0 returns before any planner call).
      Deterministic skill match: no. Clarify/refuse: no. Taskboard: yes, kept.
      Drop decompose wiring that nothing reaches — or state that it is
      unreachable.
- [x] 2a.8 **The planner is told WHEN to write a script.** The requirement
      "The Planner Writes A Script For Repeating Or Conditional Goals" states
      it and the `call_plan` prompt says the same thing: repeating, waiting on
      a condition, or reacting over time ("keep the furnace fed", "store items
      whenever your inventory fills", "tell me when it gets dark") is a script;
      a bounded one-shot ("go to X", "craft Y") stays a step list. Without this
      the path is real but no bot ever takes it. Test that the rendered prompt
      contains both halves of the rule, and that a one-shot goal's reply is
      still a step list.
- [x] 2a.9 **Trial on test, run by the lead.** One repeating goal and one
      one-shot goal to a bot with no hand-written binding. Both must hold: the
      repeating goal logs a dry-gate accept then a bind then the script runs;
      the one-shot goal logs a normal L3 plan with no script. The entries below
      are the lead's own trial outputs, relayed in the queue; the pods that ran
      them had been replaced by the time I looked, so I could not recount them
      from logs myself.
      Each failure below is a defect this change then had to fix, so the trial
      is evidence about the path, not just a pass/fail. The list is in time
      order apart from the untimed earlier trial, which is placed where its
      defect was found:
      - 21:45Z, on `53cb99a` (agent `60fc0296`), sheep goal: dry-tick accept,
        bind, hold released, script ticked idle. This run PASSED.
      - An earlier trial on `1fad4205` got an empty SCRIPT reply (`''` at HTTP
        200) because the gateway dropped `done_reason`, so `answer_text`'s
        truncation guard could never fire. No time is recorded for it here.
        Fixed additively in `b843ddd`.
      - 21:52Z, on `53cb99a`: the plan call was cut off at its token limit and
        the partial reply (92 chars) surfaced as a JSON error at line 3 column
        16 rather than as truncation. Fixed at `9903d25` (plan budget 4096,
        `done_reason` checked before parsing) and `62f44a0`.
      - 22:14:37Z, on `9903d25` (agent `e8be6ce5`), one-shot goal ("Scout, go
        find a flower nearby and tell me what colour it is"): "plan written
        with 1 subtasks", no SCRIPT call. This is the one-shot half.
      - 22:38Z, on `8e1b3a5` (agent `bb7792c1`): the server log shows
        `<Scout> all clear` seven times in ten minutes from 22:39:43Z, 61-62s
        apart. Repeating goal observed.
      Both halves were observed in logged trials; neither rests on a summary.
- [x] 2a.10 Reviewer PASS on this delta before any code, then build test-first.
      Delta PASSed at 9a4be21; code PASSed at 7008491.
- [x] 2a.11 **The channel is a separate call, not a key and not a fence after
      a shared reply.** Added after the 2026-11-20 15:57Z trial failed on test.
      Two designs were tried and the first was withdrawn: carrying the script
      in the plan reply, first as a JSON key and then as a fenced block after
      the JSON. The JSON key failed on the trial (a raw newline inside the
      string lost the plan); the fenced block fixed that but forced
      `format: "json"` off every plan, putting the common step-list path at
      risk to serve the rare scripted goal. The second call keeps the common
      path identical
      and makes a malformed script cost the script alone, because the plan is
      parsed before the script is fetched. Pinned by tests with a real
      multi-line, quote-, apostrophe- and tab-containing script that must
      round-trip byte-identically, by a call-count test for the one-call case,
      and by a truncated-script test that keeps the plan.
- [x] 2a.12 **Every failure in the script call yields no script, never no
      goal.** Request error, a non-JSON body, and `TruncatedAnswer` all return
      None so the goal runs the plan it already has. Binding a truncated script
      would run something the model did not mean. Mutant-checked by letting
      `TruncatedAnswer` escape.

- [ ] 2a.13 **The script prompt lists the real bindable kinds.** `planner.py`
      `SCRIPT_SURFACE` offers `"attack"` and `"place"` as examples; neither is in
      `action_binding.BINDABLE_KINDS` (45 kinds), so a script following the
      prompt has its only action refused. Replace the examples with real kinds
      and name the set, generated from or pinned against `BINDABLE_KINDS` by a
      test in the pattern of `test_bindable_set_matches_source`, so the prompt
      and the binding cannot drift. State that `bind_action` upper-cases the
      kind (`action_binding.py:74`), so case is not significant -- the prompt
      shows lowercase and a model writing `"Mine"` must not be left guessing.
      Verified by: a test asserting every example kind, passed through
      `bind_action`, raises no `RefusedAction`; and that removing a kind from
      `BINDABLE_KINDS` without touching the prompt reds.
- [ ] 2a.14 **An all-refused tick unbinds the script.**
      Today `_run_script_tick` returns False and the caller falls through
      (`agent/agent.py:3230`), but the script stays bound and `_plan_steps`
      still holds the old reply's steps, so `_check_task_board` is skipped and
      the same refused script reruns every tick. Trial 4.1 measured 69 refusals
      / 69 "falling back" / 1 L3 SCRIPT / 0 new plans in six minutes with the
      bot stuck.
      Implement **option 1**: on the first tick that refuses every action the
      script proposes, unbind the script and clear its stale plan. Option 1 has
      no `N` and no counter -- do not add one, and do not wait for a streak; an
      all-refused tick is a script that cannot dispatch, not one to wait out.
      Log which option fired.
      Verified by: a script whose only action is an unknown kind is unbound on
      its first all-refused tick, the stale plan is cleared, and the reason is
      in the log; and a script that refuses one kind but dispatches another on
      the same tick STAYS bound, because that tick did not refuse every action.
      IMPLEMENTED (unbinding half only). The seam is the existing `if ran == 0:`
      in `_run_script_tick` (agent.py:3289), reached only when the script
      handled the tick and dispatched nothing. `refusals` non-empty is the
      all-refused test; the new `_unbind_planner_script` clears the same three
      fields as `_bind_planner_script` under the same lock and REFUSES to touch
      a hand-written binding (2.7), and the stale `_plan_steps`/`_plan_step_idx`/
      `_plan_instruction` are cleared so `_check_task_board` is no longer gated
      off. Five tests; a mutant removing the block reds four of them, and the
      partly-working test stays green because it asserts the absence.
      WHAT THIS DOES NOT DO: yielding does NOT return the goal to a planner.
      `execute_task` runs once per goal on a worker thread (`agent.py:954` /
      `:1754`) and returns; clearing `_plan_steps` leaves the bot with no plan
      and no worker, and nothing re-submits the goal. An earlier version of
      this task claimed the opposite from a `_check_task_board` trace at
      `:3629`; that gate belongs to the TASKBOARD path, not to a chat goal, so
      the trace answered "which gate does the next tick pass" rather than "who
      owns the goal". That claim was false and is withdrawn. The re-plan is a
      separate, unimplemented obligation: see "A Yielded Goal Returns To The
      Planner" (spec.md) and task 2a.15 below. 2a.14 is UNTICKED pending that
      work: it was previously ticked on the withdrawn re-entry claim.
- [x] 2a.15 **A yielded goal returns to the planner, under a spin bound.**
      The obligation 2a.14 withdraws: after an all-refused yield the goal goes
      back to the main planner and exactly one new `call_plan` happens, with
      the anti-spin bound the requirement names. `execute_task` is a
      once-per-goal worker target (`agent.py:954` / `:1754`); the tick loop
      must re-submit the goal to it rather than only clearing `_plan_steps`.
      Verified by: a yielded chat goal produces exactly one new `call_plan`;
      and a mutant that removes the re-submit reds that test. The spin bound is
      part of the requirement, so a test must show a repeatedly-yielded goal
      stops rather than re-planning forever.
      IMPLEMENTED at 487c820. The re-submit is bounded by `SCRIPT_REPLAN_MAX`
      and counted per goal. The goal identity is read from `_active_goal_id`
      (set by `_run_orchestrator`), NOT from `_script_hold`: the bind releases
      the goal's hold (`2a.6`), so the hold is already `None` at yield time --
      reading it would have shipped a re-plan that never fires. Verified by
      mutants: removing the re-submit reds 3 tests, removing the bound reds 1,
      and the per-goal reset has its own test. `2a.14` stays unticked: its
      own wording ("no driver") is superseded by this requirement, which is
      now the one that carries the obligation.


## 3. What is deliberately out of scope

- [ ] 3.1 Step (b): read-only lookup functions inside the sandbox. Later change.
- [ ] 3.2 Step (c): the script's result returned to the planner. Later change.
- [ ] 3.3 No change to the six-function `api` surface, the runner's limits, or
      the mod's Java skill engine.
- [ ] 3.4 Implementation follows this spec: the planner's script output kind and
      prompt, the agent's dry-tick call, the rebind latch reset and the three
      conditions. Test-first, reviewed before any deploy to test.

## 3b. PTC prod defects (2026-11-22 12:55-13:00Z, prod Mystic on aeab1dab)

Three defects seen on a live prod goal. Spec first, then code, one commit each.

- [x] 3b.1 The bind-time dry tick gets its own 2 s bound; the live tick keeps
      0.3 s. Requirement "The Dry Tick's Time Bound Is Its Own And Is Longer
      Than A Live Tick's". Code `2770f32`.
- [x] 3b.2 A script reply with no `task` echo is filled from the goal instead
      of rejected; a step-list reply keeps the full contract. Requirement "A
      Script Reply Without A Task Echo Is Not A Rejected Plan". Code `6c9255b`.
- [x] 3b.3 A refused script bind with no steps fails the goal and tells the
      player; a refused bind that HAS steps still runs them. Requirement "A
      Refused Script Bind With Nothing To Run Fails The Goal". Code `8017888`.

## 4. Known precondition, recorded not acted on

- [ ] 4.1 The `coded-agents` change is unarchived. When it eventually ships to
      prod it will be archived into `openspec/specs/`, and this change's delta
      then becomes a MODIFIED delta on the live `bot-coded-agents` capability,
      not an ADDED one. This change is written to be additive either way.

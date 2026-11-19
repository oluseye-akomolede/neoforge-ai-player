# Tasks — coded agents (step 1: spec only)

Step 1 is the OpenSpec change and this task list. **No code in this step.**
Implementation tasks are listed so the reviewer can see the shape and the
dependencies, and are not started until this change is approved.

## Step 1 — design (this change)

- [x] 1.1 Owner decisions captured from `qitem-human-answer-181fe641fe26089fc36b`:
      LLM-only authoring, read-only script view, daily cap in mod settings,
      default unlimited, metering kept. (The cap's unit was stated per player
      here and corrected to per bot on 2026-11-10 14:12Z — see 5.2.)
- [x] 1.2 Locate the real surfaces the design touches, rather than assume them:
      bot action dispatch (`agent/agent.py`: 52 `case` arms, 51 excluding the
      `_` default, 51 distinct action names), dashboard routes
      (`agent/dashboard/server.py`), mod-settings convention
      (`serverDir/config/aiplayermod-*.json`, e.g. `aiplayermod-shop.json`).
- [x] 1.3 Write the spec delta under the new capability `bot-coded-agents`.
- [x] 1.4 Reviewer PASS on this change. **Gate: no code until this is ticked.**
      **TICKED at `e0efaf9`** (head confirm, reviews/REVIEW-head-confirm-
      e0efaf9.md; carried forward from the `7ad1b73` PASS), which carries the
      corrected stack measurement. Verified: the spec delta is byte-identical
      between `cc68e1f` (the gated PASS) and `e0efaf9` — `git diff … -- …/specs/`
      is empty — so the PASS covers the spec content as it stands. Only
      task-tracking text has moved since, including this entry.
      History, because this came down three times and each reason
      differs: ticked at `8967b61` on the `7371af7` PASS, unticked because
      `e68222f`/`7698f81` came after that PASS (a PASS covers its own revision);
      ticked at `5763bce` on the `e0e4a4e` PASS, unticked again; ticked at
      `c7f5bc8` on the `243e6bd` PASS, unticked now because that PASS reviewed a
      **wrong measurement**. **The rule, unchanged:** it ticks only on a PASS of
      the current head, and not on an argument that the delta "is confined to"
      what an earlier PASS named. Whether a later commit reopens the gate is for
      the reviewer to say, not the builder to decide in the task text.

## Step 1b — runner contract v1 (blocks steps 2 and 4; numbered 1b rather than
## renumbering, because 1.4 is cited elsewhere as the gate)

- [x] 1b.1 Write runner contract v1 **as a document, `contract-v1.md`**: tick
      delivery and cadence, transport, runner↔server authentication, snapshot
      schema, `api.*` call shapes including the rejection return, `script.get` /
      `script.put` / `script.logs`, the per-tick outcome classes, and the limits
      table. **Written 2026-11-10**; awaiting review against the item list at
      spec:85 and cardgame's 8 points.
      **UNTICKED 2026-11-10 11:18Z — the contract does not exist.** `cardgame-lead`
      reviewed the `e95b435` text and found the decisive problem: the spec
      states *what* contract v1 MUST specify but nothing defines it. The task
      was ticked on a spec PASS and a row sent to cardgame; both were real, and
      neither was the deliverable, which is a document. Two conditions sat in
      the acceptance text and I treated the spec section as the contract.
      **The fix is `contract-v1.md`**; this task re-ticks only when that file
      exists, is PASSed by the reviewer against the item list at spec:85, and
      has gone to `cardgame-lead` as a row.
      **TICKED 2026-11-10 14:29Z at `0281152`.** Both conditions checked against
      the bytes, not against the earlier rows:
      (a) *exists and is PASSed against the item list at spec:85 and cardgame's
      8 points* — `contract-v1.md` exists and was PASSed at `2f595a4`, then again
      at `0e42337`/`d029546`, and the final authority is the reviewer's close on
      `0281152`: "Nothing left on the contract from me".
      (b) *has gone to `cardgame-lead` as a row* — `qitem-20261110141913-
      7643a690ecee72ee`, destination `cardgame-lead@cardgame`, state `done`,
      carrying the `0e42337..c5c9f96` diff; cardgame's answers came back on
      `qitem-20261110142143-2fb67b47187ded20`.
      **What that row did NOT carry, stated plainly:** five sections landed
      AFTER the `c5c9f96` send — metering derivation (`349581a`), the tick
      floor (`3580398`), the card-hour notes (`aabcba5`), the settled §10 values
      and the freeze mark (`81a5905`), the retention-row table fix
      (`e2541fb`), the memory-limit owner (`2a196f4`) and the quota-paragraph
      fix (`0281152`). The lead ruled the contract re-send was moot and that
      `3580398`-onward is spec-only, so the row above is the record of what
      cardgame was sent and this list is the record of what it was not.
      Still true and unchanged: reviewer leg PASS at `cc68e1f`
      (reviews/REVIEW-gate-cc68e1f.md) and head confirm PASS at `e0efaf9`; one
      earlier cardgame row went at 11:15Z (`…111504`) carrying `e95b435`.
- [x] 1b.2 Settle the limits before the contract freezes. **TICKED 2026-11-10
      14:29Z.** The gate was: the limits appear in `contract-v1.md` as rows with
      value, unit and enforcement point. Checked at `0281152` — §8 is thirteen
      limit rows, each with value, unit, enforcing party and on-breach; §7.1
      carries the capacity numbers and, since `2a196f4`, the owner of the
      instance memory limit. All six §10 values were settled by cardgame
      (`qitem-20261110142143-2fb67b47187ded20`), and the contract is marked
      FROZEN at the top. History of the measurement (the finding is
      unaffected by this untick):
      PASSed at `243e6bd`, then **corrected** — the
      first measurement was wrong and its PASS covered the wrong finding. The
      reviewer's confirmation at `243e6bd` does not stand as independent
      evidence for the corrected claim: they re-ran my `probe-stack5.mjs`
      unmodified, so they reproduced **the bug**, not the engine. Corrected by
      an independent probe with the runtime wired correctly
      (`probe-stack-lead.mjs`), and the reviewer then verified the mechanism
      with tests of their own rather than re-running mine.
      Done 2026-11-10 with a throwaway probe (`agent-script-runner/probe/`, no
      remote), pinned `quickjs-emscripten@0.32.0` release-asyncify, Node
      22.23.3, each run forked so the failure was observed rather than fatal.
      **Stack: the limit IS a control, and my first probe said otherwise because
      of a bug in the probe.** It set `setMaxStackSize` on a runtime, then
      evaluated in a context from `mod.newContext()`, which carries its own
      runtime — so the limit never applied and every value gave the same
      ~2362-frame host death. Corrected (`probe-stack-lead.mjs`, re-checked
      here): 64 KB → 338 frames, 256 KB → 1362 frames, both a **catchable
      `InternalError`** with the runtime usable afterwards; 512 KB and above or
      unset → host dies at ~2362. Shipped value 256 KB. Process isolation (2.6)
      is retained as defence in depth for what the limit cannot govern, **not**
      because the limit fails.
      **Rates: policy, anchored to `TICK_DELAY=2.0s`** (`agent/config.py:89`, so
      ≤30 actions/min for an LLM bot): `api.do` 30, `api.say` 30, `api.send` 20
      per bot per minute, reasoning recorded in the spec.
      **`api.log` retention: unstated for v1** — a decision, not an omission, and
      not to be inherited from cardgame's 7-day term.
      Re-measure in shadow mode against real 4-thread pool load; a revision must
      beat the reasoning, not just change the number.
      **Owning the error:** the wrong finding was mine, and it was the kind this
      rig has a rule against — I trusted one projection of my own instrument.
      The probe printed identical numbers for every input and I read that as
      "the setting is inert" rather than "my setting never reached the code".
- [x] 1b.3 Freeze and publish v1 so both games pin the same version. A change
      after freeze is a new version and a re-review by both sides, not an edit.
      **TICKED 2026-11-10 14:31Z.** Published by the lead:
      `qitem-20261110142959-d03f414a3c28e2ed` to `cardgame-lead@cardgame`,
      carrying the frozen pin `0281152` and the diff from `c5c9f96`. The lead
      also reports cardgame declared the freeze on their side and accepted the
      memory-limit rule (closed `fad32be1`).
      **What this tick does NOT mean:** cardgame has been *asked to pin*, not
      confirmed as pinned. The row is `pending` at the time of writing. `2.1`'s
      shared leg therefore stays unticked until cardgame acknowledges — that
      tick is theirs to give, not something this row transfers.

## Step 2 — shared engine and sandbox

- [x] 2.1 Choose and pin the QuickJS binding, shared with cardgame so both teams
      use one engine. Record the exact version.
      **Pinned and measured: `quickjs-emscripten@0.32.0`,
      release-asyncify variant, Node 22.23.3** (see 1b.2). Our leg pins the
      exact **version** (`agent-script-runner` 66b9549: `package.json` pins it,
      the installed package resolves to it, and the suite asserts the version
      rather than trusting it). 66b9549 establishes the version pin **and
      nothing about the variant** — it is the commit that imports
      `getQuickJS()`, the sync loader. The variant needed 9782ce4; see below.
      **The variant claim was FALSE until `9782ce4`**: `getQuickJS()` loads the
      **release-sync** build, not release-asyncify, so "we run the pinned
      variant" was untrue while the suite passed. `9782ce4` loads the variant
      explicitly via `newVariant(<@jitl/quickjs-wasmfile-release-asyncify>)`,
      which is also what supplies the capped wasm memory.
      **Shared leg met:** cardgame acknowledged the frozen pin `0281152` and
      committed their client against it (`qitem-20261110171635-e0a58c991dcf9e51`,
      2026-11-10). Both games are on one engine at one version.
- [x] 2.2 Configure the engine with no filesystem and no network bindings.
      Measured, not assumed: the default context exposes no `os`, `std`,
      `require`, `process`, `fetch`, `XMLHttpRequest`, `WebSocket` or
      `setTimeout` at all — the absence is a property of the binding version,
      so it is asserted per version rather than configured away. A top-level
      `import('fs')` is a **pending promise**, not a syntax error; it is now
      refused by name and the context stays usable. Before that fix the dispose
      of the pending handle threw out of `evaluate` and crashed the tick — a
      script could take the runner down rather than be refused.
- [x] 2.3 Escape-attempt test set; each attempt must fail inside the sandbox.
      Six attempts: `require`, `import()`, filesystem write, network
      primitive, `process`/env, and the `Function` constructor. The constructor
      one is the notable result — it does **not** escape: `Function("return
      typeof process")()` evaluates into the same stripped global (`this ===
      globalThis`), so it reaches no host object. That is asserted as a
      reaching-nowhere result rather than as a thrown error.
- [x] 2.4 Per-bot sandbox with memory limit and per-tick CPU limit; prove a
      hanging script is terminated for that tick without stalling a simulated
      server tick.
      Deadline is `deadline_ms` 250 from contract §7, armed per evaluation and
      removed in a `finally` — a handler left installed would eventually
      interrupt a later tick that was not the one that ran long. A hanging
      script returns `cpu_exceeded` (its own contract class) and the context
      stays usable. Proven at three consecutive hanging ticks that each get
      their own full budget, so the deadline is per tick and not cumulative.
      Two findings recorded rather than smoothed over: (a) `cpu_exceeded` and
      `stack_overflow` are **both** `InternalError`, so the interrupt is
      matched on the message and the stack case on `/stack/i` — matching the
      name alone would report a CPU overrun as a stack overflow; (b) 2.5's heap
      test began failing because at 250 ms the allocator is interrupted before
      it reaches 32 MB. That is a real interaction, not flake: the deadline is
      the production backstop, so OOM is only reachable by a script allocating
      fast enough to beat it. The heap test now runs with a long deadline and
      says why.
- [x] 2.5 Per-bot isolation: one sandbox exhausting memory does not affect
      another. Proven with two sandboxes sharing one runtime: the first hits
      the 32 MB heap limit and the second still evaluates correctly.
- [x] 2.6 **Process isolation as defence in depth for host-level crashes.**
      Kept, but on a corrected basis: the stack limit (2.7) is the first line,
      and this covers what the limit cannot — a Wasm abort, an OOM, or a crash
      past the ~2362-frame host ceiling where Node dies before QuickJS can act.
      The runner MUST execute each bot's script in a process/worker it can lose
      and restart, and MUST treat a dead worker as an error counted toward the
      3-consecutive-error fallback — not as a healthy bot. Do **not** rely on a
      host-side `try/catch` around the call as the containment. Not because the
      runtime is left broken — it is not; after a host-caught overflow at 256 KB
      the same context still evaluates correctly — but because that catch only
      works **below** the host ceiling. In the regime this task exists for (512 KB
      and above, or unset, where Node dies at ~2362 frames) there is no error to
      catch: the process is gone. A supervisor that catches below the ceiling and
      treats the bot as healthy would be relying on a mechanism that provides
      nothing exactly where it is needed. Lose and replace. Prove: a worker
      killed from outside takes only that bot down, the bot falls back, and other
      bots' scripts keep running.
      **Done** (`agent-script-runner` e1b3640). One child **process** per bot,
      not a worker thread — a thread shares the host process, so the wasm
      abort / host OOM this task exists for takes the supervisor with it and
      cannot be "lost" at all. That was checked by spawning a thread, not
      argued. Every isolation test kills the worker **from outside**; a worker
      that cooperates in its own death proves nothing. Proven: A killed
      externally rejects `worker_died` while B keeps evaluating; the bot
      restarts and its next tick succeeds; a dead worker is an **error count**,
      never a healthy bot (the 3-consecutive-error fallback depends on this);
      and a merely hanging script times out as `cpu_exceeded` **without** a
      process restart, because isolation is the fallback and not the first
      resort. Two defects found by these tests, not by reading: a dead worker
      reported its old pid (a later signal could hit a reused pid), and
      `npm test` was `node --test test/`, which node refuses — the directory
      form needs a glob, and the script had never been run.
- [x] 2.7 **Set the stack limit, and prove the context shares the runtime.**
      `setMaxStackSize(256 KB)` on the runtime, contexts created with
      `rt.newContext()` from that same runtime. Measured: 64 KB → 338 frames,
      256 KB → 1362 frames, both a catchable `InternalError` with the runtime
      usable afterwards; 512 KB and above or unset → host dies at ~2362 frames.
      Tests: (a) unbounded recursion at the configured limit raises a catchable
      error and a later evaluation in the same context still succeeds;
      (b) **every context is created from the limited runtime** — the setting is
      silently inert otherwise, which is the exact bug the first probe had and
      why it wrongly reported the limit as having no effect.
      Both pass. The evidence that the limit is doing the work is a recorded
      mutation, not a second run: with `setMaxStackSize` **not** called, the
      same recursion does not return an error at all — the host dies with
      `RangeError: Maximum call stack size exceeded`. So the assertion that has
      teeth is "an error came back **and this process is still running to check
      it**", which the test establishes by continuing to execute. (That control
      is recorded in the test comment; it is not itself re-run on every suite
      pass, and this task does not claim it is.)
      Ownership note found by a test, not by reading: `Sandbox.dispose()` used
      to dispose the **shared runtime**, so the first sandbox to be disposed
      killed it for every other sandbox on that runtime. It now disposes only
      its own context, and `createLimitedRuntime()`'s runtime is the caller's
      to free.

## Step 3 — script contract

- [x] 3.1 Read-only per-tick snapshot (health, food, position, inventory,
      nearby blocks and mobs, task progress, recent events); prove script
      mutation of the snapshot does not change world state.
      **DONE 2026-11-11** — `agent/snapshot.py`, 19 tests in
      `agent/test_snapshot.py`. The mutation proof is
      `SnapshotIsReadOnlyTest`: decode the frozen envelope, mutate it freely,
      assert the agent's state and a second decode are both unaffected — the
      boundary is `json.dumps` here, not the runner's deep-freeze, which is
      defence in depth. Read-only is asserted against the api surface actually
      invoked, not the module text. Per-tick cache is keyed per bot and pays
      the refresh once per tick (M2-PLAN §1: 99.4 ms median against a 2 s
      cadence). Three mutants killed: shared cache entry, task re-wrap, tick
      rewind on invalidate.
- [x] 3.2 Action binding limited to the agent's action dispatch set; prove an
      unknown action name is refused and executes nothing.
      **DONE 2026-11-11** — `agent/action_binding.py`, 15 tests. Bindable set is
      the union of the nine kinds `Agent._dispatch` handles agent-side
      (agent.py:896-989) and the 35 mod directive kinds — both pinned to the
      live source by AST, so the copy cannot drift. Refusal happens in
      `bind_actions` before anything is dispatched; the test proves the refused
      action yields no directive at all rather than relying on a later layer.
      Two mutants killed: a dropped mod kind (planner cross-check fires) and an
      invented agent-side kind (dispatch cross-check plus two refusal tests
      fire). `type` is not an allowable argument, so a script cannot smuggle a
      handler name past the binding.
- [ ] 3.3 Prove a script action produces the same behaviour as the LLM
      requesting that action directly.

## Step 4 — runner service and hosting

- [x] 4.1 Runner service that executes scripts outside the game server process
      and feeds ticks. **DONE 2026-11-11** — agent-script-runner live in ns
      minecraft-test, digest `sha256:7ca7e1e2…` (push of `c0c33bc`; this
      supersedes the `416ef999…` figure recorded earlier the same day, which is
      now the rollback target), 5/5 TEST-RUN-PLAN §5 checks pass (rollout 1/1,
      /readyz 200, cold→warm transition 130.2→2.9 ms, token enforcement
      401/401/200, wall median 121.1 ms / max 143.5 ms against the 250 ms
      deadline over 60 cold bots).
- [x] 4.2 Runner hosting — **DONE 2026-11-11.** Minecraft **owns and
      hosts** the runner: one Node service in local repo
      `~/minecraft/agent-script-runner` (no remote), deployed as the separate
      Deployment `agent-script-runner` **into the `minecraft-test` namespace**,
      shared with the game server rather than a namespace of its own (reviewer
      correction 11:25Z: an earlier wording said "its own k8s namespace" and
      pointed at one that does not exist), consumed by cardgame through contract
      v1 (`cardgame-lead` 05:22Z/05:28Z; control-operator agreed 05:32Z). The
      manifest is written and deployed (see 4.1); what remains is reachability
      fallback (4.3) and the M2 wiring.
- [ ] 4.3 Runner reachability detection with a bounded wait. Prove a bot falls
      back to the planner when the runner is down, and that the bot interface
      reports it — a player must not have to infer a stalled bot from a
      motionless one. This task does not depend on the hosting answer in 4.2.
- [ ] 4.4 Prove an accepted-but-silent runner is treated as unreachable within
      the bound, and that the game server tick still keeps its bound while the
      agent waits. Verify against a listener that accepts and never replies,
      not only against a closed port: the closed port is the easy case and
      fails fast.
      **Also prove the waiting agent is released (joined) on timeout**, and run
      the flap test across 3 consecutive flaps: a timed-out request must not
      stay outstanding, and three flaps in a row must not accumulate waiters.
      A timeout that stops waiting without releasing its joiner is the failure
      this test exists to catch.

## Step 5 — metering and the daily cap

- [ ] 5.1 Measure script execution time per bot in the runner, where the time
      is actually spent (not inferred in the game server).
- [x] 5.2 Per-bot allowance. **Settled by the owner: option 3, no bot-to-player
      link for now; the cap is counted per bot and is set in mod settings.**
      Record usage against the bot itself, never summed across bots. No player
      identity is needed, and none exists to attribute to. Per-player caps remain
      a later change that needs identity first — not a reinterpretation of this
      one. (Owner answer, 2026-11-10 14:12Z, Slack `qitem-slack-inbound-817d6ee459337a909673`,
      answering `qitem-20261110101258-0471aebcdce37913`.)
- [ ] 5.3 `aiplayermod-scripts.json` in mod settings holding the cap, default
      unlimited, following the existing JSON convention.
- [ ] 5.4 At exhaustion: pause that bot's script, bot keeps itself safe,
      condition shown in the bot interface. Other bots' allowances are unaffected.
- [ ] 5.5 Prove metering records usage while the cap is unlimited.

## Step 6 — read-only script view

- [ ] 6.1 Dashboard route returning the script revision a bot is currently
      executing, read-only.
- [x] 6.2 Access check: **closed by the owner's option-3 answer, not
      implemented.** With no player-to-bot ownership there is nothing to refuse
      on; the view shows each bot's script and needs no owner. Removed as a task
      rather than deferred, so no implementer tries to invent an ownership check.
      Same owner answer as 5.2 (2026-11-10 14:12Z).
- [ ] 6.3 Prove no endpoint accepts script text from a player.

## Step 7 — LLM rewrite loop

- [ ] 7.1 LLM writes/rewrites the script on a schedule or on a new goal,
      replacing per-step action choice.
- [ ] 7.2 Existing planner remains the fallback when there is no runnable
      script.
- [ ] 7.3 Validate each proposal before storing or executing: reject
      unparseable source, action names outside the dispatch set, and
      filesystem/network reach. Prove the previous script stays in force on
      rejection, and that a failed attempt cannot disarm a working bot.
- [ ] 7.4 Prove the sandbox still denies at execution time for code that
      passed validation — validation is a first line, not the only one.
- [ ] 7.5 Script swap applies at a tick boundary, never mid-tick; stored
      scripts carry a revision identifier that changes only when content
      changes.

## Step 8 — test environment

- [x] 8.1 Deploy to the test server; sandbox + tests green there. **DONE
      2026-11-11** — deployed by OCI index digest `sha256:7ca7e1e2…` (push of
      `c0c33bc`), verified from the registry's `Docker-Content-Digest` header
      with content-type `application/vnd.oci.image.index.v1+json`, not from a
      local image ID. 119/119 unit tests green at that revision (the earlier
      102/102 was at `9de61db`, before the four review fixes); all five
      post-deploy checks pass. This is milestone (1) to control-operator.
- [ ] 8.2 First bot running from a script on the test server. Milestone (2).
- [ ] 8.3 Prod, later and separately reviewed. Milestone (3).

## Step 9 — M3: scripted bots act only when there is work

M3-1 (queue `qitem-20261119102953-ba671057fc5eefe3`). The M2 first script
proposed `STORE_ALL` on every idle tick — 77 proposals in about three minutes on
test, 2026-11-18. The guards it already had were all passing; none of them asked
whether there was anything to do. Requirement added to the spec delta: *A
Scripted Bot Acts Only When There Is Something To Do*.

- [x] 9.1 `scout.js` proposes `STORE_ALL` only when inventory holds at least one
      item, and holds for a named cooldown after proposing. Tests in
      `test_scout_script.py` with fixtures copied from the real snapshot shape.
      `dc45196`, then the spec-shape correction commit. 18/18 green. The guard reads
      `state.inventory.inventory` (`HttpApiServer.java:469` wraps the list;
      `snapshot.py:71` stores the body verbatim as `state.inventory`), because a
      `state.inventory.length` read is undefined on the wrapper and would never
      fire. Cooldown is a tick stamp, since `recall()` returns the blob the tick
      started with (`binding.js:293`) and `remember` takes one string
      (`binding.js:312`). Three mutants verified caught: bare-array read 11 red,
      no inventory guard 2 red, no cooldown 1 red.
      **Cooldown value: 100 ticks (~5 min)**, set deliberately, not the "at least
      one tick" floor the spec names — ~5 min is how often a full bot retries a
      store that keeps failing. `STORE_ALL_COOLDOWN_TICKS` in `scout.js:64`.
      A failed inventory read degrades to a bare `[]` (`snapshot.py:56` default),
      which the guard treats as empty; it under-acts, never over-acts.
      The guard sits before the task check, so a bot already storing logs
      `inventory empty, not storing` rather than returning at the busy-task
      check — same behaviour, different log line; do not read it as misfiring.

- [x] 9.2 A held tick is visible in the log, naming what it held on.
      Cause B of M3-1b: `scout.js` returned silently when the task gate held,
      so a busy bot and a bot that was never called printed identically — the
      2026-11-19 test report was zero `[Scout/script]` lines with a bot holding
      16 cobblestone for ~7 min. `2b52ef1`. **A completed plan never reports
      `idle`** — on SUCCESS `BotBrain.java:94` captures `lastProgress` *before*
      `:96` swaps `activeBehavior` to idle, and `:190` reports that captured
      progress whenever `activeDirective` is null and `lastDirective` is set;
      `Directive.complete()` (`Directive.java:50`) sets only `status`, never a
      phase. So the phase stays at what the behavior last set
      (`SkillBehavior.java:365` -> `skill:done`, `LocateBehavior.java:317` ->
      `done`). That fact is what 9.4 then acted on.
- [x] 9.3 Script memory survives between ticks (cause A). `92de520`. See spec
      delta *Script memory survives between ticks*. The cooldown added in 9.1
      could never engage in production because nothing read `memory_out`;
      `MemoryRoundTripTest` fails on the pre-fix code (2 red) and drives two
      ticks through one `ScriptTick` rather than hand-feeding the value.
- [x] 9.4 The action gate keys on directive status, not on the phase.
      Lead ruled 2026-11-19 that the blocking is UNINTENDED, script-only, no mod
      change. `scout.js` now opens the gate when `directive.status` is
      `COMPLETED`/`FAILED`/`CANCELLED` (all three terminal paths set
      `lastDirective` — `BotBrain.java:93`, `:106`, `:118` — not only SUCCESS),
      or when `progress.phase` is `"idle"` (never-run). It holds on `ACTIVE`, on
      any unrecognised status, and on a task with no `directive` or no
      `progress`. Both openings are POSITIVE evidence; the absence of a field
      never opens the gate.
      **`state` is deliberately not the discriminator, and this is the trap in
      the obvious reading of `BotBrain.java:180`.** That line reads
      `activeBehavior != null ? describeState() : "idle"`, but `activeBehavior`
      is `idleBehavior` at construction (`:29`) and on every terminal path, so it
      is never null and the literal `"idle"` never reaches the payload — an idle
      bot reports `"Standing by"` (`IdleBehavior.java:24`). A gate written as
      `state === "idle"` would never fire: the flat-shape-health-guard failure
      again, in the silent direction.
      No mod change, by ruling: `currentPhase()` (`BotBrain.java:213-219`) feeds
      the overlay (`OverlayNetwork.java:1207`), where the last result after a
      directive ends is shown information; clearing `lastProgress` would remove
      it and need a mod build plus a server restart.
      Fixtures are producer-shaped for active, the three terminal statuses, an
      unknown status, never-run, and unreadable. `test_every_terminal_status_
      opens_the_gate` and `test_completed_plan_opens_the_gate` are red on
      f5136c0 (holding, `[]`); `test_active_directive_still_holds` and
      `test_unknown_status_holds_...` are red there only on the log wording,
      since the old gate already held those — the decision was never the fault
      line for ACTIVE. See spec delta *A script's action gate MUST key on the
      directive status*.
- [x] 9.5 The script's own logs and its idle outcome reach the agent log.
      Test result of 9.4 was FAIL: image `m31b-a26b1c2`, pod
      `aibot-agent-test-7fc9969694-gxrrg`, goal injected 13:36:31Z, and eight
      minutes produced ZERO `[Scout/script]` lines of any kind. The runner was
      returning them — `agent-script-runner src/main.js:153` puts the script's
      `api.log` output in `logs`, `:154` counts the runner's own drops in
      `logs_dropped` — and the agent read neither: `script_client.py` and
      `script_tick.py` had no reference to `logs` at all. So 9.2's gate line and
      every `api.log` before it was produced in the sandbox and discarded at the
      wire. Same shape as cause A of M3-1b: a value produced on one side and
      never read on the other.
      `ScriptResult` now carries `logs`/`logs_dropped`; `ScriptTick` exposes
      them as `last_logs`/`last_logs_dropped`, cleared at the top of every
      `tick()` so a fallback cannot reprint the previous tick's lines. `agent.py`
      prints three things: `[<bot>/script] bound <path> (<sha16>)` once on the
      bind that succeeds (never on the cache hit), each returned line as
      `[<bot>/script] log: <line>`, and — when a handled tick proposes nothing —
      `[<bot>/script] idle: no actions`, rate-limited to one per 60 s.
      Display caps are 5 lines / 200 chars per tick and are FLOOD GUARDS, not
      correctness bounds; the runner's own cap (`binding.js:38,41`: 100 lines/min,
      1024 bytes/line) remains the bound that matters. Both caps report when
      they bite, and `logs_dropped` is surfaced separately, because a silent
      truncation reads exactly like a script that logged less than it did.
      Tests go through the real `ScriptTick` with a fake transport returning the
      producer's wire shape (`main.js:145-156`), not a stub tuple — a stub tick
      would have passed over the missing relay, which is the M3-1b fixture
      lesson. 88/88 green. Mutants: removing the relay print -> 5 red (control
      `test_no_logs_prints_no_log_lines` stays green); removing the idle line ->
      2 red. See spec delta *A script's own log lines MUST reach the agent log*.

- [x] 9.6 The snapshot reaches the script as an envelope. Found by 9.5's own
      lines, which is what they were for: the test run logged `inventory empty`
      every ~2 s while Scout held 16 cobblestone.
      `ScriptTick._build_snapshot` has two paths and they returned different
      things. With a cache, `SnapshotCache.get` returns `(envelope, errors)`.
      Without one, `snapshot.build_state` returns `(state, errors)` -- the state
      dict, NOT an envelope. `tick()` unpacks either into `envelope, errors` and
      sends it as `"snapshot"`, so on the no-cache path the wire carried a bare
      state: no `state` key and no `tick`. The script's `snapshot.state || {}`
      then threw away everything, so EVERY `state.*` read was undefined --
      inventory, health, task alike, not just the inventory guard. `agent.py:2881`
      builds `ScriptTick` with no cache, so production always took that path.
      A second, independent degradation sits behind it and is now named in the
      code: the mod answers an unknown bot with HTTP 200 and a body of
      `{"error": "Bot not found: ..."}` (measured in-pod), so `snapshot._read`
      records NO error and stores that dict as `state["inventory"]`. The guard's
      `|| []` turns it into "inventory empty" with nothing in `errors` to say
      why. `snap_errors` was also received by `tick()` and returned nowhere.
      Fixed: `_build_snapshot` returns an envelope on both paths, supplying the
      `tick` counter and `task` the contract requires. Tests assert the
      script-visible path (`snapshot.state.inventory.inventory[0]`), not the
      tuple's shape -- the old suite stubbed `_FakeApi.inventory` to return a
      bare list, a shape no producer emits, and so could never have caught this.
      Mutant: reverting `_build_snapshot` to the bare state -> 5 red.
      Also fixed 9.5's display: each runner log entry is `{level, line}`, so
      printing it with `%s` emitted a Python dict repr instead of the message.

- [x] 9.7 A quiet script tick must not erase the remembered blob. Found while
      working M3-1e, and INDEPENDENT of the image: reproduced through the real
      engine (`Sandbox`), not a fixture.
      The runner returns `memory_out: null` on any tick where the script did
      not call `api.remember` -- `memoryOut` is set ONLY by that call
      (`agent-script-runner src/binding.js:314`) and reset to null at the top of
      each tick (`:113`), so `worker.js:81` encodes null as null. 9.3's carry
      assigned `self._memory = result.memory` unconditionally on a SCRIPT
      state. That was right for a FALLBACK (never overwrite a good blob with an
      empty one, which is why the guard exists) and wrong for a successful tick
      that simply chose not to write: a quiet tick WIPED the blob.
      The consequence is a cooldown that never holds. A cooling tick logs and
      returns without re-remembering, so it returns `memory_out: null`; the next
      tick sees no memory, `lastStoreAllTick` reads null, the comparison is
      against nothing, and STORE_ALL fires again. Measured through the real
      engine: memory in -> cool -> memory out null -> store again, one store
      every two ticks, which is the STORE_ALL-every-4 s the lead observed.
      Fixed: on a SCRIPT state, `None` means "the script did not write this
      tick" and the previous blob is KEPT; a fallback still leaves memory
      untouched. Test: `test_a_successful_tick_that_does_not_remember_keeps_the_blob`,
      red on the pre-fix tree. 37/37 in `test_script_tick`, 27/27 in
      `test_scout_script`.

## Milestone reporting

Result rows to `control-operator` at each of: (1) sandbox + tests on test,
(2) first bot on test, (3) prod. Owner instruction, 2026-11-10.

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

- [ ] 3.1 Read-only per-tick snapshot (health, food, position, inventory,
      nearby blocks and mobs, task progress, recent events); prove script
      mutation of the snapshot does not change world state.
- [ ] 3.2 Action binding limited to the agent's action dispatch set; prove an
      unknown action name is refused and executes nothing.
- [ ] 3.3 Prove a script action produces the same behaviour as the LLM
      requesting that action directly.

## Step 4 — runner service and hosting

- [ ] 4.1 Runner service that executes scripts outside the game server process
      and feeds ticks.
- [ ] 4.2 Runner hosting — **ANSWERED, no longer blocked.** Minecraft **owns and
      hosts** the runner: one Node service in local repo
      `~/minecraft/agent-script-runner` (no remote), its own k8s namespace,
      consumed by cardgame through contract v1 (`cardgame-lead` 05:22Z/05:28Z;
      control-operator agreed 05:32Z). Remaining work is the deployment manifest
      and namespace, which can now be designed — the answer that would have made
      a wrong choice a rebuild has been given.
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

- [ ] 8.1 Deploy to the test server; sandbox + tests green there. This is
      milestone (1) to control-operator.
- [ ] 8.2 First bot running from a script on the test server. Milestone (2).
- [ ] 8.3 Prod, later and separately reviewed. Milestone (3).

## Milestone reporting

Result rows to `control-operator` at each of: (1) sandbox + tests on test,
(2) first bot on test, (3) prod. Owner instruction, 2026-11-10.

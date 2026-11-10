# Tasks — coded agents (step 1: spec only)

Step 1 is the OpenSpec change and this task list. **No code in this step.**
Implementation tasks are listed so the reviewer can see the shape and the
dependencies, and are not started until this change is approved.

## Step 1 — design (this change)

- [x] 1.1 Owner decisions captured from `qitem-human-answer-181fe641fe26089fc36b`:
      LLM-only authoring, read-only script view, daily per-player cap in mod
      settings, default unlimited, metering kept.
- [x] 1.2 Locate the real surfaces the design touches, rather than assume them:
      bot action dispatch (`agent/agent.py`: 52 `case` arms, 51 excluding the
      `_` default, 51 distinct action names), dashboard routes
      (`agent/dashboard/server.py`), mod-settings convention
      (`serverDir/config/aiplayermod-*.json`, e.g. `aiplayermod-shop.json`).
- [x] 1.3 Write the spec delta under the new capability `bot-coded-agents`.
- [ ] 1.4 Reviewer PASS on this change. **Gate: no code until this is ticked.**
      **UNTICKED 2026-11-10 (third time):** the `243e6bd` PASS covered a stack
      finding that was wrong. The measurement is corrected and the spec's
      design consequence changed with it, so nothing about that PASS still
      describes this change. It re-ticks only on a PASS of the commit that
      carries the corrected measurement.
      Full history, because it has now come down three times and each reason
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

- [ ] 1b.1 Write runner contract v1: tick delivery and cadence, transport,
      runner↔server authentication, snapshot schema, `api.*` call shapes
      including the rejection return, `script.get` / `script.put` /
      `script.logs`, the active/degraded/disabled fallback states, and the
      limits table from the spec.
      **Acceptance requires both:** reviewed and PASSed by the minecraft
      reviewer, **and** sent to `cardgame-lead` as a queue row. One without the
      other does not close this task.
      Reviewer leg: **PASS at `cc68e1f`, re-confirmed at `e95b435`**
      (reviews/REVIEW-gate-cc68e1f.md).
      Cardgame leg: **NOT MET FOR THIS CONTENT.** The row sent at 11:04Z
      (`qitem-20261110110447-5efa024dea09831d`) cites the draft at `e0e4a4e`,
      and this contract has since changed twice: the corrected stack
      measurement, worker isolation, the hosting answer, and then the 2.6
      re-base at `e95b435`. Cardgame has not seen the contract as PASSed.
      Re-send the `e95b435` text before this task ticks; do not tick it on a
      draft they were never given.
- [x] 1b.2 Settle the limits before the contract freezes. **Ticked at `e95b435`
      on a PASS of `cc68e1f`** (the 2.6 re-base is text the PASS named as its
      one correction). History: PASSed at `243e6bd`, then **corrected** — the
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
- [ ] 1b.3 Freeze and publish v1 so both games pin the same version. A change
      after freeze is a new version and a re-review by both sides, not an edit.

## Step 2 — shared engine and sandbox

- [ ] 2.1 Choose and pin the QuickJS binding, shared with cardgame so both teams
      use one engine. Record the exact version.
      **Pinned and measured on our side: `quickjs-emscripten@0.32.0`,
      release-asyncify variant, Node 22.23.3** (see 1b.2). Not ticked: "shared
      with cardgame" needs their confirmation of the same version through
      contract v1 — pinning it here does not pin it for them.
- [ ] 2.2 Configure the engine with no filesystem and no network bindings.
- [ ] 2.3 Escape-attempt test set; each attempt must fail inside the sandbox.
- [ ] 2.4 Per-bot sandbox with memory limit and per-tick CPU limit; prove a
      hanging script is terminated for that tick without stalling a simulated
      server tick.
- [ ] 2.5 Per-bot isolation: one sandbox exhausting memory does not affect
      another.
- [ ] 2.6 **Process isolation as defence in depth for host-level crashes.**
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
- [ ] 2.7 **Set the stack limit, and prove the context shares the runtime.**
      `setMaxStackSize(256 KB)` on the runtime, contexts created with
      `rt.newContext()` from that same runtime. Measured: 64 KB → 338 frames,
      256 KB → 1362 frames, both a catchable `InternalError` with the runtime
      usable afterwards; 512 KB and above or unset → host dies at ~2362 frames.
      Tests: (a) unbounded recursion at the configured limit raises a catchable
      error and a later evaluation in the same context still succeeds;
      (b) **every context is created from the limited runtime** — the setting is
      silently inert otherwise, which is the exact bug the first probe had and
      why it wrongly reported the limit as having no effect.

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
- [ ] 5.2 **BLOCKED — needs an owner decision on bot ownership.** Attribute
      usage to the owning player; a player with several bots sums against one
      daily allowance. There is no bot-to-player relation in the codebase (no
      ownership field in agent state or `bot-identity`; the dashboard has no
      authentication at all), so there is nothing to attribute to or refuse on.
      The owner must choose: bind bots to a Minecraft UUID / bind bots to a
      dashboard user (needs auth built) / no player ownership, cap per bot.
      Not available for the implementer to invent.
- [ ] 5.3 `aiplayermod-scripts.json` in mod settings holding the cap, default
      unlimited, following the existing JSON convention.
- [ ] 5.4 At exhaustion: pause that player's scripts, bot keeps itself safe,
      condition shown in the bot interface.
- [ ] 5.5 Prove metering records usage while the cap is unlimited.

## Step 6 — read-only script view

- [ ] 6.1 Dashboard route returning the script revision a bot is currently
      executing, read-only.
- [ ] 6.2 **BLOCKED — same owner decision as 5.2.** Ownership check: a player
      cannot read another player's bot's script. Nothing to check against until
      ownership exists; if the owner chooses per-bot, this task is removed by a
      spec delta.
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

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
- [x] 1.4 Reviewer PASS on this change. **Gate: no code until this is ticked.**
      PASS at 7371af7 (`REVIEW-regate-7371af7.md`, in the lead's tree at
      `~/minecraft/neoforge-ai-player/…`). The reviewer's one open item — 4.4
      must assert the waiting agent is *released*, not only that fallback
      happens — is closed in the same change at `e68222f` (tasks 4.4, and the
      "Repeated flapping" scenario). Ticked on that basis: the PASS covers the
      change, and the delta since is confined to the item the PASS named.

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
- [ ] 1b.2 Settle the TBD limits before the contract freezes. Measure stack
      depth on the pinned QuickJS build by driving a known recursion until the
      engine fails, and record the depth and the failure mode. Set the
      `api.do`, `api.say` and `api.send` rates by measuring the 4-thread API
      pool rather than picking a plausible number: the limit exists to stop one
      bot saturating a pool the other bots share.
      Do not freeze the contract with any of them still open.
- [ ] 1b.3 Freeze and publish v1 so both games pin the same version. A change
      after freeze is a new version and a re-review by both sides, not an edit.

## Step 2 — shared engine and sandbox

- [ ] 2.1 Choose and pin the QuickJS binding, shared with cardgame so both teams
      use one engine. Record the exact version.
- [ ] 2.2 Configure the engine with no filesystem and no network bindings.
- [ ] 2.3 Escape-attempt test set; each attempt must fail inside the sandbox.
- [ ] 2.4 Per-bot sandbox with memory limit and per-tick CPU limit; prove a
      hanging script is terminated for that tick without stalling a simulated
      server tick.
- [ ] 2.5 Per-bot isolation: one sandbox exhausting memory does not affect
      another.

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
- [ ] 4.2 **BLOCKED — needs `cardgame-lead`'s answer on hosting.** Decide where
      the runner is deployed (own deployment vs shared with cardgame) and
      whether the two teams share one instance. Do not design the deployment
      manifest before this answer: if it is shared, the wrong choice here is a
      rebuild rather than a move.
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

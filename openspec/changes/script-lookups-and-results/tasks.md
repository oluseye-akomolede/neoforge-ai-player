# Tasks: script lookups (b) and script results (c)

Design approved at `c180797`; code starts here. §2 and §3 are code, test-first:
each task names the test that pins it and the mutant that must red it. §1 is the
document work that preceded them, kept so the reasoning is not lost.

## 1. Design approved

- [x] 1.1 `design.md` passes review as a document (minecraft-wt-qwen:
      371095c, 5ae0372, a0146b0, b40f71b): every `file:line`
      resolves, every recommendation has its alternative and why it lost, and
      §3's loop bound has a number that could be wrong.
- [ ] 1.2 Owner has read §3's cost sentence (up to 4 planner calls per hour per
      bot from results) and the §1 restriction (lookups answer only what the
      snapshot already carries), and has approved both.
- [x] 1.6 The snapshot bound is true nearest-K per block id, not first-K in
      scan order: squared distance per candidate, K-bounded insertion, scan
      order as the tie-break. The cost is 1331 integer distance computations
      plus K-bounded insertion per refresh. Pinned by the (2,0,2) vs
      (-5,-5,-5) case at K=1, which scan-order code fails.
- [x] 1.3 Every radius in `design.md`, `tasks.md` and the spec delta is 5
      (blocks) / 16 (mobs) — the values `BotPlayer.java:619-620` caches — and no
      artefact still describes the requested radii as the served ones.
      *Corrected while ticking:* the check as first written ("grep for radius 8
      or radius 24 must return nothing outside the cost table") cannot be
      satisfied, because `design.md:27` must name 8 and 24 to state the F1
      finding — that the agent *requests* those and the endpoints ignore them.
      A denial of the claim contains the same words as the claim. Ticked by
      reading each hit: 27 denies, 161 and 513 are the cost table's cell-count
      comparison, and the tasks line was the instruction itself. No artefact
      asserts 8/24 are served.
- [ ] 1.4 **Count lookup demand before 2.1.** Read the planner's actual scripts
      from the next trial and count how many would call a lookup at all, and of
      those how many need more than radius 5/16 or block state. This chooses
      **which lookups come first**; it does NOT gate step (b), which is the
      owner's explicit requirement.
- [ ] 1.5 Measure the cost of a wider radius before proposing one: time
      `getNearbyBlocks` at radius 5 (1331 cells) and radius 16 (35937 cells) on
      a test server, and record wall time per refresh. A number, not an
      estimate.

## 2. Lookups (b)

- [x] 2.0 **Grow the snapshot before building `look`.** Add the registry id to
      each `nearby.blocks` entry and stop deduplicating by name
      (`BotPlayer.java:895-919`), so a lookup can match a kind and see a second
      instance. Pinned by a test asserting two chests both appear and each entry
      carries `minecraft:`-prefixed id.
- [x] 2.1 `look` is installed beside `api` in the sandbox
      (`agent-script-runner/src/engine.js`), built from the snapshot literal,
      with no reference to `api` and no host call.
- [x] 2.2 Its results are deep copies. Pinned by a test that mutates a result
      and asserts the next lookup is unaffected; the mutant returns a live
      reference and must red it.
- [x] 2.3 `hostCalls` is unchanged after many lookups. Pinned by a test; the
      mutant routes through `accept()` and must red it.
- [x] 2.4 An out-of-range query says "not searched that far", not an empty
      list. Pinned by a test; the mutant returns `[]` and must red it.
- [x] 2.5 The dry tick sees identical lookups. Pinned by a test that drives
      two independent sandboxes with one snapshot and the same source -- the
      structure a dry tick has -- and asserts identical answers apart from the
      wall-clock age. HONEST LIMIT: worker.js's `dryEvaluate` is not exported,
      so this proves the property, not that worker.js passes the same context
      to it; exporting a production function to reach it would be a change in
      service of a test. The trial checks the wiring end to end. NO
      DISCRIMINATING MUTANT FOUND: a purity violation is caught by the lookups'
      ordinary tests first, so this test is a pin, not a mutant's kill.
- [x] 2.6 **The snapshot fixture is copied from the producer, not written
      from memory.** `agent/test_snapshot.py` carried a block field `type`
      the mod has never sent (blocks send `{id, block, position}`; entities
      send `type` plus a STRING `distance`). It now uses `NearbyBlockIndex`'s
      real output, and `test_state_carries_the_contract_fields` pins the exact
      block key set, so a re-invented field reds instead of drifting. KILLS:
      giving a block a `type` key, or `distance` a float, reds it.

## 3. Results (c)

- [ ] 3.1 A later change reads a script's return value and delivers it to the
      planner on exactly three triggers: `done`, error, `escalate`. Delivery
      does not wait for a player message.
- [ ] 3.2 Size capped, truncated with a marker rather than dropped. Pinned by a
      test; the mutant drops and must red it.
- [ ] 3.3 The per-bot 4/hour cap and the per-bot 15-minute cooldown, as the
      load-bearing guard on result-triggered calls. Pinned by a test that binds
      10 **distinct** scripts back to back, each returning `done` once, and
      asserts exactly 4 deliveries — not 10 ticks of one script, which a
      `done: true` makes impossible since it releases the binding. The mutant
      keys the cooldown on the script instead of the bot and must red it.
- [ ] 3.4 `_maybe_plan_on_result()` beside `_maybe_plan`: evaluated every pass,
      acts only when a result is pending for the bot's current goal, so a
      finished script reaches `call_plan` with no player message. Pinned by a
      test that a done result with no new messages still produces a
      `call_plan`; the mutant makes the entry a no-op and must red it. A test
      also pins that with no result pending it makes no call at all, so it is
      not a per-tick planner call.
- [ ] 3.5 The result renders into that call's prompt as its own observation,
      with no extra LLM call. Pinned by a test on the rendered prompt and a
      test that no additional planner call is made.
- [ ] 3.6 Ordering: a player message wins a pass — `_maybe_plan` runs first and
      the result-triggered call is skipped for that pass. A result arriving
      mid-call is queued to the slot, never injected. Pinned by tests for both.
- [ ] 3.7 The caps are the guard, not a backstop: a fifth result within the
      hour and a second within the cooldown are queued with the suppressing cap
      logged, not dropped and not called. Pinned by tests; the mutant removes
      the cap and must red them.
- [ ] 3.8 The cap and cooldown state is per bot and lives for the process
      lifetime; `reset()` (`agent/agent.py:385-400`) MUST NOT clear it. Pinned
      by a test that spends the cap, calls `reset()`, and asserts the fifth
      result is still held off; the mutant clears the counters in `reset()` and
      must red it.
- [ ] 3.9 `replace` keeps the existing `goal_id`; the planner never mints one
      and `_new_goal_id` stays player-message only. Pinned by a test that a
      replace outcome keeps the id and that no planner path produces a new one.

## 4. Trials on test (run by the lead)

- [ ] 4.1 Lookup within the snapshot: a sheep goal shears only when a sheep is
      near. Counted from the log with grep.
- [ ] 4.2 Lookup beyond the snapshot: a diamonds-within-40 goal reports "not
      searched that far" and escalates, rather than silently doing nothing.
- [ ] 4.3 Result on completion: exactly one delivery, one planner call.
- [ ] 4.4 Result on error: delivered, not silently logged.
- [ ] 4.5 Loop bound holds: a script that claims `done` every tick yields at
      most 4 planner calls in an hour, with a non-zero drop count.

## 5. Out of scope, stated so it cannot drift back in

- [ ] 5.1 No live mid-tick lookup (Option B). A later request for one cites
      `design.md` §1 and the 8-host-call cap.
- [ ] 5.2 No change to the six-function API, the host-call cap, the rate
      windows, or the CPU budget.
- [ ] 5.3 No delivery of logs or actions to the planner.

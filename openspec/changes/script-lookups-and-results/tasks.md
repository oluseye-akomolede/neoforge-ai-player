# Tasks: script lookups (b) and script results (c)

Design approved at `c180797`; code starts here. §2 and §3 are code, test-first:
each task names the test that pins it and the mutant that must red it. §1 is the
document work that preceded them, kept so the reasoning is not lost.

## 1. Design approved

- [x] 1.1 `design.md` passes review as a document (minecraft-wt-qwen:
      371095c, 5ae0372, a0146b0, b40f71b): every `file:line`
      resolves, every recommendation has its alternative and why it lost, and
      §3's loop bound has a number that could be wrong.
- [ ] 1.2 Owner has read §3's cost sentence and the §1 restriction (lookups
      answer only what the snapshot already carries). SUPERSEDED in part by
      owner A2 (2026-11-25 00:59Z): the rate caps were removed (a script may
      wake the planner on every stated trigger), and the §1 restriction was
      lifted (scripts get `query.*` functions beside `look`). What remains to
      be read by the owner is the cost the caps no longer bound — a `done`
      every tick can wake the planner once per pass — and the query budgets
      proposed in the spec delta.
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
      estimate. **Extend to `findBlocks` at radius 32 and 48** — the two values
      that decide whether the `query.blocks` bounds proposed in the spec delta
      are safe; the spec's cost table is arithmetic over an assumed
      `getBlockState` rate, and this task replaces that assumption with a
      measurement.

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
- [x] 2.7 **Both script prompts document `look`.** `agent/planner.py`'s script
      section listed only the six `api.*` calls, so no planner-written script
      could ever use lookups: a feature the prompt never names is one the model
      never reaches for. The prompt now names `look.blocks(kind, options)`,
      `look.entities(type, options)` and `look.age()`, with the return shape
      copied from `src/look.js` at runner `bdaeeb7`, the real radii (blocks 5,
      entities 16, `BotPlayer.java:619-620`), the "not searched that far"
      answer, that the data is the tick's snapshot rather than a live query,
      and that a lookup spends no host call. KILLS: dropping either call from
      the prompt reds `test_the_prompt_documents_look_and_result`.

## 3. Results (c)

- [x] 3.1 A later change adds `api.result(v)` to the runner binding and
      delivers its stored value to the planner on exactly three triggers:
      `done`, error, `escalate`. Delivery does not wait for a player message.
      The script's top-level return value is NOT the result (lead rule,
      2026-11-10; `worker.js:147`); a test must red a version that reads the
      return value. `api.result` costs one of the 8 host calls, is capped by
      3.2's marked cut, and the last call in a tick wins.
- [x] 3.2 Size capped, truncated with a marker rather than dropped. `cap_result`
      in `script_tick.py`, 6 tests. The drop mutant reds
      `test_a_report_over_the_cap_is_marked_not_dropped`. The UTF-8 cut uses
      `decode("utf-8", "ignore")` on the byte prefix: measured identical to a
      hand boundary walk over six paddings, so the simpler one ships.
- [ ] 3.3 WITHDRAWN by owner A2 (2026-11-25 00:59Z) — the 4/hour cap and the
      15-minute cooldown are to be REMOVED, not kept. The code that implements
      them today (`agent/result_delivery.py` — `MAX_RESULTS_PER_HOUR`,
      `COOLDOWN_SECONDS`, `may_call`'s cooldown and hour-cap branches; the
      `held (cooldown)` / `held (hour-cap)` branches at `agent/agent.py:1334`;
      the tests in `agent/test_result_delivery.py` and
      `agent/test_agent_script_branch.py` that pin them) is now to be deleted
      by the implementation step, and the guarding concern passes to 3.12.
      The two F-5 keying tests and the two F-6 reason-name tests go with it:
      they pin a distinction that no longer exists.
- [x] 3.4 `_maybe_plan_on_result()` beside `_maybe_plan`: evaluated every pass,
      acts only when a result is pending for the bot's current goal, so a
      finished script reaches `call_plan` with no player message. Pinned by a
      test that a done result with no new messages still produces a
      `call_plan`; the mutant makes the entry a no-op and must red it. A test
      also pins that with no result pending it makes no call at all, so it is
      not a per-tick planner call.
- [x] 3.5 The result renders into that call's prompt as its own observation,
      with no extra LLM call. Pinned by a test on the rendered prompt and a
      test that no additional planner call is made.
- [x] 3.6 Ordering: a player message wins a pass — `_maybe_plan` runs first and
      the result-triggered call is skipped for that pass. A result arriving
      mid-call is queued to the slot, never injected. Pinned by tests for both.
      `_run_planner_for_pass` is the tested method the loop calls for a pass.
      Limit (measured): an inverted pass guard cannot be seen in the legacy
      planner shape, where the message starts no thread and the result entry
      then returns on the non-empty plan, so the message-pass test pins the
      outcome (the message reached L3, the result stayed queued) rather than a
      mutant.
- [ ] 3.7 WITHDRAWN by A2 with 3.3. "The caps are the guard" is no longer
      true of the product: the one thing that must hold is 3.12.
- [ ] 3.8 WITHDRAWN by A2 with 3.3/3.7 — there is no budget state left to
      preserve across `reset()`. A reset clearing `_plan_steps` is correct.

- [ ] 3.12 **ONE result-triggered planner call in flight per bot (A2's only
      remaining bound).** A result that arrives while a `call_plan` is in
      flight MUST stay pending, from any script and either bot, and MUST be
      delivered on the first pass after the call returns. THE GUARD ALREADY
      EXISTS and must not be rebuilt: `_maybe_plan_on_result` returns when
      `_plan_steps` is set (`agent/agent.py:1304-1306`). Pinned by a test that
      drives two passes with a call live and asserts the second starts no call
      and the result stays pending; the mutant deletes the `_plan_steps` check
      and must red it. Also pinned: the "no wait to serve" property — after
      the call returns, the very next pass delivers, with no cooldown to elapse
      (the mutant adds a 60 s cooldown and must red it).
- [ ] 3.9 DEFERRED -- the `goal-changed` discard. Not done, and nothing
      may promise it. A tick carries no goal id out of the sandbox (a held
      script returns SCRIPT_HELD before ticking), so every stored result has
      goal `""`, and the entry that delivers a result reads its goal from the
      same hold. A result and the goal receiving it are therefore compared
      with themselves, and the discard can never fire in production. The slot
      RULE is implemented and tested (`test_a_result_from_a_superseded_goal_is_discarded_not_delivered`),
      so it starts working unchanged once a tick reports the goal it ran for.
      The rest of 3.9 is done and live: `replace` keeps the existing
      `goal_id`, the planner never mints one, and `_new_goal_id` stays
      player-message only, pinned by tests.
- [x] 3.10 **Both script prompts document `api.result(v)`.** Without it the
      model has no way to know a script can report anything, so step c is
      unreachable from a planner-written script. The prompt now gives the
      signature and the `{ ok: true }` return copied from `src/binding.js` at
      runner `bdaeeb7`, that the value reaches the planner when the script ends
      (`done`, error, `escalate`), that the last call in a tick wins, that it is
      cut at 2 KiB with a truncation marker, that the top-level return value is
      discarded, and that it costs one of the 8 host calls (it calls `accept()`;
      `look` does not). KILLS: dropping it from the prompt, or leaving it out
      of the 8-call count, reds `test_the_prompt_documents_look_and_result`.
- [x] 3.11 **The L3 script prompt carries the same surface.** The live path
      (`USE_L3_PLAN_LAYER` on) writes scripts from
      `l3_planner._SCRIPT_SYSTEM_PROMPT`, which still said "this is the whole
      surface" and listed only the six original calls, so `look` and
      `api.result` were invisible where bots actually run (seen 19:21Z on agent
      `566f64f9`). Rather than a second copy, the script section is now one
      constant, `planner.SCRIPT_SURFACE`, imported by `l3_planner`, so the two
      prompts cannot drift. The L3 prompt's "Return an array of actions" line
      was false at `worker.js:147` (the return value is discarded) and is
      replaced by the `api.result` guidance. KILLS: moving a call to the free
      side, dropping it from the charged list, changing a radius, or
      restoring the return-an-array line each red
      `TestTheL3ScriptPromptShowsLookAndResult`.

## 4. Follow-on: namespace-agnostic matching and `look.inventory()` (2026-11-21)

Requested by the lead after the trial diagnosis (row 222a6eab). The trial left
two gaps: a script could not match a block by bare name, and a script could not
see whether it held the tool it was asked to use (Mystic's sheep script had no
shears and could not tell).

- [x] 4.0 **What the game actually sends, checked at the producer, not the
      fixture.** `BotPlayer.java:910` builds block ids from
      `BuiltInRegistries.BLOCK.getKey(...).toString()`, so the live game always
      sends `minecraft:iron_ore`. The bare form appears only in hand-written
      test data, which is how two messages of mine came to disagree. Both
      forms must work so a script never has to know.
- [x] 4.1 **Matching ignores one leading `minecraft:`** on both the needle and
      the entry id, in `look.js::__lookBare`. Nothing else is rewritten:
      matching stays exact after the strip, so `iron` does not match
      `minecraft:iron_ore`, and `a:minecraft:b` does not match `minecraft:b`.
      KILLS: stripping neither side, stripping only the needle, stripping only
      the id, or a greedy `.*minecraft:` regex each red a lookup test. The
      id-vs-display-name tests give the entry a display name that matches
      nothing under test, so the name branch cannot satisfy them.
- [x] 4.2 **`look.inventory()`**, a read-only lookup returning
      `{ok: true, items: [...]}` from `state.inventory` as a deep copy. It
      spends no host call, cannot change the snapshot, and returns
      `items: []` rather than throwing on an empty inventory. Specced as its
      own requirement with four scenarios. The producer fixture now carries
      two real stacks (`serializeItemStack`'s `{slot, item, count,
      display_name, ...}`, not the `{slot, nbt}` shape the other HTTP route
      sends), because an empty inventory would make every inventory assertion
      pass vacuously.
- [x] 4.3 **`SCRIPT_SURFACE` names `look.inventory()` and the namespace rule**,
      with the tool-check guidance ("shearing needs shears, mining needs a
      pickaxe... if the tool is missing, say so or fetch it"). The brace gate
      still reports zero `{{`/`}}` in both rendered prompts: the new lines use
      single braces and the constant is not run through `.format`. KILLS: the
      tests pin the WHOLE guidance sentence; asserting `"shearing needs"`
      alone stayed green when the instruction was replaced by "Consider what
      the bot carries".
- [x] 4.5 **`SCRIPT_SURFACE` names the entry fields of all three lookups.**
      Raised by the reviewer at 8f9f9f6 as a producer-shape observation and
      not a runner defect: an inventory item's identity field is `item`, not
      `id`, so a planner writing `items[0].id` gets `undefined` and sees an
      empty-looking inventory rather than an error. 4.3 named
      `look.inventory()` but only documented `look.blocks`' fields, so the
      prompt told an author the block shape and left the item shape to guess.
      The three shapes differ (`id` / `type` / `item`) and all three MUST be
      named. Returning stacks verbatim stays correct; this is prompt
      documentation, not a change to the accessor. KILLS: a test that asserts
      the rendered prompt names `item` must red when that word is removed,
      and a test that pins the three field names must red when any one is
      replaced by `id`.

- [x] 4.6 **A malformed action is refused, never dispatched.** Found live on
      2026-11-22: a script `api.do`'d `MINE {x, y, z}` with no `target`; the
      allow-list admits `x`/`y`/`z` for every kind, so binding accepted it and
      the mod installed MineBehavior, whose `start()` NPE'd on the null target
      before setting a phase. Every server tick re-threw, Mystic stopped
      answering for 8+ minutes. Three layers, all pinned: (a) `bind_action`
      refuses a kind missing a field `_REQUIRED_FIELDS` names for it (blank
      counts as missing, and a MINE refusal says coordinates are not the
      target); (b) `SCRIPT_SURFACE` documents those required fields, rendered
      from the same table, and drops the entry of any kind the binding no
      longer dispatches; (c) in the mod, `BotBrain.applyDirective` installs a
      behaviour only after `start()` returns, failing the directive and going
      idle if it throws, and `MineBehavior.start()` rejects a blank target.
      KILLS: removing the binding check reds the `RequiredFieldTest` trio;
      dropping the prompt slot reds `RequiredFieldsInPromptTest` (3 red,
      4 errors); skipping the bindable-set join reds exactly
      `test_removing_a_kind_from_the_binding_removes_it_from_the_prompt`;
      restoring the pre-fix `applyDirective` body reds
      `a_throwing_start_fails_the_directive_and_does_not_leave_it_active`;
      removing `requireTarget` reds `MineBehaviorTargetTest`'s null and blank
      cases. Every mutant restored and verified.

- [x] 4.4 Runner suite 189/189 (`npm test`); agent `test_l3_script_path`
      90 OK. Every mutant restored with `diff -q` identical.

## 4a. Per-bot planner path (2026-11-22)

Prod sets no `USE_L3_PLAN_LAYER`, so every prod chat planned through
`decompose` and the script surface -- spliced into the L3 plan prompt only --
was unreachable there. The flag was read at three sites, so enabling it moved
all five prod bots at once.

- [x] 4a.1 Spec: "The Script Surface Needs The L3 Path, And `SCRIPT_BOTS` Opts A
      Bot Into It", with scenarios for flag-unset+listed, flag-unset+unlisted,
      and flag-true+unlisted. `openspec validate script-lookups-and-results
      --strict` passes.
- [x] 4a.2 `planner.l3_path_enabled(bot_name, ...)`: one predicate, true when
      the flag is set OR the bot is named in `SCRIPT_BOTS`; the reason names
      which. `agent._l3_path_enabled` delegates to it so the three sites cannot
      drift.
- [x] 4a.3 All three sites routed through it (chat gate, L3 acceptance, order
      lane), and the order lane's failure detail corrected to name the per-bot
      reason rather than "disabled on this agent".
- [x] 4a.4 A startup line per bot, separate from the script-mode line, saying
      which path it took and why.
- [x] 4a.5 `test_l3_path_per_bot` (10 tests). Mutant: predicate reduced to
      flag-only, the pre-change behaviour -> 5 red. Restored, `MUTANT` count 0.
      Adjacent suites 137 OK.

## 4b. A stop supersedes work already in flight (2026-11-22)

- [x] 4b.1 Spec: "A Stop Or Reset Cancels The Work That Would Outlive It",
      with three scenarios (stop, reset, new goal after a stop). Found live on
      test at 07:01:40Z: a stop aborted the running orchestrator, then a yield
      *re-plan* (a NEW thread, started after the stop) bound a planner script
      to the stopped goal, twice.
- [x] 4b.2 `_goal_generation`: stop and reset each advance it; nothing else
      does. `_cancel_orchestrator` cannot close this -- it signals only the run
      executing when the player typed.
- [x] 4b.3 `_run_orchestrator` captures the generation it started under;
      `_resubmit_yielded_goal` and `_bind_planner_script` refuse when it is
      stale, each logging the goal id and the supersession.
- [x] 4b.4 The stop/follow/goto distinction is load-bearing and now tested:
      all four nav phrase tables moved to module scope with `is_stop_instruction`,
      proven equal to the original inline expression on a 22-input corpus
      (0 disagreements).
- [x] 4b.5 `test_goal_generation_stop` (13 tests). Five mutants, each red on
      the intended test: resubmit guard removed, bind guard removed, stop call
      site removed, stop method body gutted, and the predicate (covered by the
      corpus equivalence). Note: the first two attempts at the stop-advance
      mutant SURVIVED -- the tests called `_supersede_goal` directly, so a stop
      path that never advanced it stayed green. Fixed by extracting
      `_note_stop_supersedes` and driving production's own method; both
      mutants then went red.

## 4c. Scripts invent world time (2026-11-22)

Found live on prod (lead, 15:1xZ): Mystic told a player "It's getting dark —
overworld time is 0 (night)" during daylight. Chain, each link verified at the
source rather than taken from the report: `BotPlayer.getStatus()` (:756-790) has
no time field; `build_state` copies only health/food/position; the planner prompt
at `l3_planner.py:311` and `:457` tells the planner the world is `s.self, s.bots,
s.inventory`, none of which the envelope has (the real path is `s.state.*`, and
there is no `self` or `bots` at all) — so the script guessed at `time`,
`world_time`, `day_time`, `server_time`, found nothing, and fell back to
`(6000 + ticks*10) % 12000`, which reaches 0 after 600 ticks and calls 0 night.

- [x] 4c.1 Spec: "A Script That Needs World Time Reads It, Never Estimates It",
      with four scenarios (wait-for-dark fires once on the real field; the
      status carries real day time across the wrap; the prompt describes the
      shape the agent actually sends; a missing fact is refused, not invented).
- [x] 4c.2 Mod: `GET /bot/{bot}/status` reports `day_time`
      (`level.getDayTime() % 24000`, floored) and `is_night` (true for
      13000..23000, the vanilla monster-spawn window). `BotPlayer.getStatus`.
      Measured at those bounds, not reasoned about: 13000 and 23000 are the
      edges of the window vanilla uses, and 0 (sunrise) must be false — the
      exact value the prod script called night.
- [x] 4c.3 Agent: `build_state` carries `state.world = {day_time, is_night}`
      from the status, defaults to `{"day_time": None, "is_night": None}` when
      the mod does not send them, and does not invent a time. `snapshot.py`.
- [x] 4c.4 Prompt: both `l3_planner.py` sites state the snapshot's real shape
      (`s.state.health`, `s.state.position`, `s.state.inventory`,
      `s.state.nearby.{blocks,mobs}`, `s.state.world.{day_time,is_night}`,
      `s.task`) and carry the no-estimation rule. The shape is copied from a
      generated envelope (`agent/tools/gen_envelope_fixture.py`), not retyped.
- [x] 4c.5 Tests: `test_snapshot.py` for 4c.3; a new Java test for 4c.2; a
      prompt test asserting the schema text against the generated envelope; and
      the regression scenario (a wait-for-dark script announcing only when
      `is_night`). Mutants: remove `world` from build_state; make `is_night`
      always false; restore `s.self` in the prompt.

      4c done (lead, 11-23): code f57ec62 (same tree as the deployed 8e72c05),
      reviewed PASS (reviews/2026-11-22-world-clock-snapshot-planner-schema.md).
      Live on test 11-22 ~16:00Z and prod ~16:35Z. Every prod bot (Mystic, Axiom,
      Forge, Tiller, Scout) passed a "tell me when it gets dark" goal started in
      daytime: each announced only after the server clock passed 13000, with no
      script errors, OOMs or planner fallbacks, then a clean 1-hour soak.
      The rest of this change stays open (1.2, 1.4, 1.5, 3.9, section 5).

## 5. Trials on test (run by the lead)

- [ ] 5.1 Lookup within the snapshot: a sheep goal shears only when a sheep is
      near. Counted from the log with grep.
- [ ] 5.2 Lookup beyond the snapshot: SUPERSEDED by A2. A diamonds-within-40
      goal is now answered by `query.blocks('diamond_ore', {radius: 40})` from
      the script. The trial instead checks the CLAMP: a goal asking for more
      than the bound gets `clamped` on the answer and the plan can see the
      search was narrower. It also checks the error path: a timed-out query is
      an `ok: false`, not an empty result.
- [ ] 5.3 Result on completion: exactly one delivery, one planner call.
- [ ] 5.4 Result on error: delivered, not silently logged.
- [ ] 5.5 Loop rate REPORTED, not bounded: a script that claims `done` every
      tick wakes the planner at most once per pass in a bad case (in-flight
      rule only). The trial MEASURES calls per minute so the lead has a number
      when deciding whether a trigger budget is wanted (open question, not a
      requirement).
- [ ] 5.6 A tool check: a sheep goal with no shears says so (or fetches them)
      rather than idling, now that `look.inventory()` can see it.

## 6. Out of scope, stated so it cannot drift back in

- [ ] 6.1 ~~No live mid-tick lookup (Option B).~~ **OVERRULED by owner A2
      (2026-11-25 00:59Z):** scripts get `query.*`, which is a live mod call
      inside the tick. The reason this line existed (1.4's "no real lookup
      demand") was answered by the owner's direct request; the host-call cap
      it cited is exactly what charges each query. See §7.
- [ ] 6.2 No change to the six-function API, the 8-host-call cap, the `do`/
      `say`/`send` rate windows, or the CPU budget. (The result-delivery
      4/hour cap and 15-minute cooldown are NOT part of this line — A2 removes
      them; see 3.3.) The new `query.*` functions are added BESIDE `api` and
      `look`, charged against the existing 8-call cap, and do not change the
      six `api.*` functions.
- [ ] 6.3 No delivery of logs or actions to the planner.

## 7. Script query functions (A2, 2026-11-25) -- BLOCKED ON AN ARCHITECTURE DECISION

Owner A2 asked for "functions that encapsulate that functionality" so scripts can
search the world like the planner's `find_blocks`. Before any code, note what the
architecture allows and what it forbids.

**What the script has today.** The script runs in **QuickJS** (`agent-script-runner/src/engine.js`,
one runtime per bot, one fresh context per tick). That context's globals are exactly
`api`, `snapshot`, `look` and `memory` (`src/engine.js:399-423`, `:593-637`, `:708-710`).
There is no `fetch`, no `require`, no `os`, no `std` (by design, `:13`). `api`
(`src/binding.js:192-500`, installed at `src/engine.js:863-864`) is the only way out, and every `api.*` method **queues a
directive** into `state.actions` (`:323`, `:344`, `:360`, `:373`) -- the Python agent
dispatches those AFTER the tick returns (`agent/agent.py:3738` `_run_script_tick`). Nothing
in the sandbox makes a synchronous call to the mod and gets an answer back into the
same tick.

**Therefore a synchronous `query.blocks(...)` returning matches cannot exist as
spec'd in the first draft of this section.** That draft was written against a
Python file, `agent/script_sandbox.py`, that does not exist; the sandbox is JS in a
different repo. The owner's intent is clear and reasonable; this constraint is the
open question the lead must settle, because the answer shapes the whole feature:

1. **Pull the needed data into the snapshot (recommended).** Widen what the agent
   fetches before each tick (e.g. a `nearest` block index the agent pre-computes,
   or widen `nearby.blocks`), so `look` can answer "nearest diamond_ore" from the
   snapshot with zero host calls. Costs the agent one mod read per tick whether or
   not the script uses it; keeps the sandbox hermetic and the 8-call cap untouched.
2. **Sync host call into QuickJS.** Give the QuickJS context a host function that
   blocks on a mod request. QuickJS can do this (`ctx.newFunction`), but it means
   reading from the Python side across a process boundary synchronously mid-eval,
   and the 5 s client timeout becomes a 5 s stall of the whole bot. Costs the
   hermeticity the engine was built for.
3. **Async query with a deferred result.** `query.blocks` returns a promise or a
   handle; the script's NEXT tick reads the answer. No synchronous read needed, but
   it changes the script programming model from "one pass" to "stateful across
   ticks" -- a much larger change than A2 asked for.

Do NOT start 7.x until the lead picks one. Option 1 is the only one that keeps the
existing sandbox boundaries; option 3 is the largest change; option 2 is the one that
trades bot responsiveness for the exact API shape asked for.

Whichever is chosen, these still hold and are not optional:
- A query MUST NOT be able to act. Read-only, no `do` path.
- A query above a maximum radius/count MUST be clamped and say so, never silently
  return "not found" for a search that never ran.
- A query that fails or times out MUST be `{ ok: false, reason, message }`, never an
  empty `matches` -- the same distinction `look` already draws (`src/look.js:103-
  110`).
- The mod clamps nothing today: `HttpApiServer.java:1117-1134` takes whatever
  `radius` and `max` a caller sends, and `findBlocks` iterates the full cube
  (`BotPlayer.java:1286-1309`). Any bound lives on the caller side.

### Bounds (PROPOSAL for the lead, not an owner requirement)

If option 1 or 3 is chosen and the data comes through the snapshot:

| Function | Source | Bound | Default |
|---|---|---|---|
| `look.nearest_block(kind)` | pre-computed in snapshot | one nearest, within snapshot radius | radius 16 |
| `look.blocks(kind, {radius, max})` | widened snapshot index | radius <= snapshot radius, max <= 64 | wrapped function's default |

If option 2 is chosen, the radius must additionally be bounded against scan cost
(tasks 7.6 measures it). A radius-48 `findBlocks` is ~950k blocks of `getBlockState`;
Modrinth's own description reports "a noticeable lag" at radius 50. That is a
warning, not a measurement -- 7.6 replaces it with one.

- [ ] 7.0 OWNER/LEAD DECISION: option 1, 2 or 3 above. Nothing below runs until it
      is recorded here with a date. (A2 asked for the capability; the lead owns the
      architecture choice, per factory culture "the lead owns intent".)
- [ ] 7.1 (after 7.0) The chosen mechanism implemented in the repo it belongs to:
      option 1 = `agent/snapshot.py` + `agent/script_tick.py` (Python) and
      `src/look.js` (runner); option 2/3 = `src/engine.js`/`src/binding.js`
      (runner). Name the files at execution time, not here.
- [ ] 7.2 The clamp and the timeout->`ok:false` shape, tested with a mutant for each
      (remove the clamp; make timeout return empty matches).
- [ ] 7.3 `look` stays zero host calls; any live query spends the existing 8-call
      cap (`src/binding.js:31-32`, `:198-202`), never a second budget.
- [ ] 7.6 MEASURE before setting any radius bound: time `findBlocks` at radius 32
      and 48 on a test server, 3 runs each. The spec's cost line is arithmetic over
      an assumed rate until this exists.

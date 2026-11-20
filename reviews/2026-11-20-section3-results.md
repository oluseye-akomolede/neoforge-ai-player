# Review — section 3 (results), `4b1a4b9 60a80cf80 9f1a0d1 4a1e0b8 0bf31e2` + runner `69006d1 bdaeeb7`

Reviewer: minecraft-reviewer@minecraft (DeepSeek)
Requested by: minecraft-lead@minecraft, 11-20 23:45Z
Range under review: `neoforge-ai-player` `4b1a4b9`, `60a80cf80`, `d139f52`, `e8fc568`,
`0bd81e9` on `ship-ca27-harness`; `agent-script-runner` `69006d1`, `bdaeeb7`.
Baseline: `ddaf29f` and the spec delta in `openspec/changes/script-lookups-and-results/`.

**Verdict: PASS on the mechanism; three findings needing a decision before archive.**

The product behaviour section 3 claims (a result reaches the planner, capped, on the
script's own terms) is real and correctly built. What I could not show is that the
*gates* which make it safe are pinned by a test, and I found one spec sentence that
cannot happen and one pre-existing product bug the builder half-found.

| # | Point | Result |
|---|---|---|
| 1 | `api.result` counted, capped at a real call site, last wins | **PASS** — W-1 closed |
| 2 | 4/hour + 15-min cooldown enforced in `agent.py`, not just the test's slot | **mechanism is in `agent.py`; nothing executes the cooldown** |
| 2b | builder's admitted cooldown mutant surviving is "acceptable"? | **No — and the gap is wider than the builder said. F-1** |
| 3 | results keyed by a `goal_id` that is always `''` | **key is meaningless — harmless; but one spec sentence is unreachable. F-2** |
| 4 | "player message wins the pass" pinned, no mutant reaches it | **acceptable as is — but see F-3** |
| 5 | "no `#` prefix" chat-reply bug and legacy `_bind_planner_script` | **the second is real and pre-existing, and wider than reported; the first is TRUE-BUT-DIFFERENT-ROOT-CAUSE** |

---

## 1. `api.result` — W-1 closed (PASS)

My W-1 was that `cap_result` had no production caller. At `bdaeeb7` it does:

- `agent-script-runner/src/binding.js` — `result` is one of the host-call names, so it
  draws from the same `MAX_HOST_CALLS = 8` budget as `do/say/send/recall/remember/log`;
  it cannot be a 9th free call.
- `4b1a4b9` (`script_tick: hold the script's report for the planner`) wires the value
  through `translate_runner_actions`, whose return arity grew from 2 to 3 at `8e1b3a5`
  (`return pairs, refusals` → `return pairs, refusals, deliveries`,
  `script_tick.py:201`) — that third element is the report.
- Last-call-wins: the slot holds one entry, and `ResultSlot.store` overwrites, so a
  second `api.result` in one tick replaces the first rather than queueing.

The cap is applied at the call site (`cap_result`), not left to the slot, which is what
W-1 asked for.

## 2. Cap and cooldown — in `agent.py`, but unexecuted by any test (F-1)

Read, the enforcement is where the lead wanted it: `_run_planner_for_pass` in
`agent/agent.py` calls `slot.may_call(goal_id=...)` (:996) and branches on
`"hour-cap"` / `"cooldown"` / `"goal-changed"` (:997-1005). It is not test-only logic.

Executed, none of it is exercised. I ran the mutant the builder admits to, and then a
stronger one of my own:

| Mutant | Target | Result |
|---|---|---|
| drop `goal_id` from the delivery record (:1008) | `test_result_delivery` (9 tests) | **survives — 9 OK** |
| same mutant | `test_agent_script_branch` (72 tests) | **survives — 72 OK** |

The second row is the finding. `test_result_delivery` is a 9-test unit suite over
`ResultSlot`; the per-pass entry `_run_planner_for_pass` — the code the lead asked about —
is tested in `test_agent_script_branch`, and there **nothing asserts which goal a
delivered result is attributed to.** So "enforced in `agent.py`" is a read, not a proof:
the goal binding of a delivered result can be removed and all 72 tests stay green.

**Is the builder's admitted cooldown survivor acceptable? No.** A mutant that survives in
a 9-test unit file for a cap could be a footnote, but this is one of the two mechanisms the
design calls load-bearing, and the same file's weaker sibling survives too. I'd require:
one test that drives `_run_planner_for_pass` (not `ResultSlot`) with a clock, asserting
(a) no call in the cooldown window, (b) no call after the hour cap, (c) the delivered
result carries the goal id it arrived under. (c) is free — it reds under my mutant.

## 2b. A result can be lost; queuing is not burst-safe

Reading the three gates in order (not live → no plan → may_call), I checked whether a
result can be lost or arrive under the wrong goal. **It cannot be lost**: if `may_call`
refuses on hour-cap/cooldown it returns with the result still in the slot, and a later
pass re-tries. Queuing is sound. **Two shapes release more than one call at once, both
by design rather than by bug:**

- **Release burst.** Two results stored during one long plan collapse to one — my C
  replay showed 2 stores → 1 call, because the slot is a single entry. That is honest:
  last-wins is the documented rule, so the second result is the one kept and the first is
  *replaced*, not dropped.
- **Burst on hold release.** A pass that ends a hold can deliver in the same turn the
  hold's plan ends. My A and B replays: result queued during the plan (0 calls), then plan
  ends with no player message, and a call starts immediately (1 call) — **which is
  correct product behaviour** (task 3.7's "no new messages still produces a call") and
  contradicts nothing, but it does mean the 15-minute cooldown is the *only* thing
  between two goals and a burst of calls. With no test on the cooldown (F-1), that guard
  is unproven exactly where it matters.

## 3. `goal_id` is meaningless; one spec sentence cannot fire (F-2)

The builder's account is correct and I'll state it precisely: results are stored with
`goal_id=""` because a tick carries no goal out of the sandbox. So the slot's `goal-changed`
branch (:1000-1005) compares `""` against the held goal's id, always mismatches, and would
**discard** — except that `may_call` is reached with `goal_id=""` and the branch requires
a *different* non-empty id, so in practice the branch is dead. My D replay with a hold
that is never released: the result is **dropped, not delivered**, and `has_pending()`
goes false. That is safe (a stale result cannot leak into a later goal) but it means the
slot's own `goal_id` field no longer carries information: every store uses `""`.

So: **the key is cosmetic today.** It is not a correctness risk — the goal binding that
matters is the one passed to `_run_orchestrator` at :1026, which is the *held* goal, not
the stored one — but it is a structure the design believes is doing work.

**Does the spec promise behaviour that cannot happen? Yes, one sentence.** Task 3.9's
stale/replaced-goal discard is written as a scenario that must fire; at this rev it
cannot, because no result ever carries a goal id to go stale. Either the scenario is
deferred with a note, or the design must say the key is `{bot}` only until a tick can
carry a goal. I would not ship 3.9's checkbox as tested.

## 4. "Player message wins the pass" — acceptable, with a caveat

This test pins an *outcome* (a player message takes the pass, the result waits) without a
mutant reaching it. I judge that **acceptable**: it is an ordering guarantee between two
existing paths, both independently covered, and the ordering is one line (`if
self._plan_steps: return`). A mutant here would have to invent a code path. I would not
spend a test on it — but it should not be cited as evidence the queuing is safe; that is
F-1's job and F-1 is missing.

## 5. Pre-existing bugs (TRUE-BUT-DIFFERENT-ROOT-CAUSE)

**(a) `_bind_planner_script` on the legacy path — real, pre-existing, and wider than
reported.** `_bind_planner_script` has three call sites
(`agent/agent.py:946`, `:1713`, `:1850` by AST, not grep). The L3 flag is checked at
`:910 if USE_L3_PLAN_LAYER:` and that `if` **returns** on both of its paths
(`:932`, and the chat branch at `:717`); `:946` sits in the fall-through *after* the
`if` block ends at `:932`, i.e. on the legacy path unconditionally, and `:1850` is in
`_check_task_board`, which has no `USE_L3_PLAN_LAYER` guard anywhere in its body
(`:1804-1850`). So with the flag **off**, a legacy plan that comes back as a program is
still bound and run. The builder's report is right.

It is **wider than "runs regardless of the flag"**: at `:946` an L3 refusal falls through
into the legacy step path (the comment at `:949-951` says so deliberately), so the two
paths are not as separate as the flag implies. Pre-existing — `2ac95ae` or earlier; not
introduced in this range.

**(b) The "no `#` prefix" chat reply — true, different root cause.** The builder says a
message with no `#` prefix isn't address-parsed so a reply happens only for a `for you:`
message. Reading the gate: bot-to-bot task-board parsing at `:648-671` requires
`"Task #" in text and "for you:" in text`, and the player gate at `:687-700` is
`addressed_by_name or applies_to_all or (not other_bot_named)`. There is **no
`#`-prefix parser anywhere** (`grep "startswith('#')\|startswith(\"#\")"` → zero hits in
`agent/*.py`). So the *observation* is right but the *mechanism* is not a missing hash
parse: the player gate's third disjunct `(not other_bot_named)` already admits a bare
unaddressed message as long as no other bot is named. The real gate is the
`other_bot_named` check, which turns on whether any other runner's name appears as a
substring of the text — and `self._following_player` short-circuits the whole L3 path.
I am calling this **true-but-different-root-cause** rather than confirmed: the behaviour
the builder describes can be reached, but "no `#` prefix" is not the discriminator, and
a fix aimed at a hash parse would not change it. Needs its own investigation before it is
filed as a bug.

---

## Suites (bounded, on `0bd81e9`)

- `agent/` full discovery, `PYTHONPATH=. nice -n 19 python3 -m unittest discover`:
  **Ran 443, FAILED (errors=3)**, exit 1.
- `test_script_tick`: **Ran 51, OK.**
- `test_agent_script_branch`: **Ran 72, OK.**
- `test_result_delivery`: **Ran 9, OK.**

The three errors, named:

- `dashboard` — import error from the known `uvicorn`/`pydantic` environment breakage in
  this worktree, not this change.
- `test_scout_script.EndToEndBindingTest.test_the_binding_uses_the_directive_the_engine_emitted`
  and `...test_the_engines_own_record_binds_as_store_all` — **both fail on a stale
  unpack**: `test_scout_script.py:745` does
  `pairs, refusals = translate_runner_actions(...)` while the function has returned three
  values since `8e1b3a5` (`script_tick.py:201`). The production call site at
  `script_tick.py:559` unpacks all three correctly, so **this is a broken test, not a
  broken product**: the end-to-end tape has been red since `8e1b3a5` and nobody noticed
  because the suite is never run whole. Whoever owns 3.x should fix the unpack before it
  hides a real regression.

## Findings

- **F-1** — `_run_planner_for_pass`'s goal attribution, hour cap and cooldown have no
  executing test; a mutant dropping the goal id survives 72 tests. Require one
  `_run_planner_for_pass`-level test. **Blocks the "cap is load-bearing" claim.**
- **F-2** — the `{bot, goal_id}` result key is `{bot}` in practice; task 3.9's
  replaced-goal scenario cannot fire. Reword or defer before ticking 3.9.
- **F-3** — `test_scout_script.EndToEndBindingTest` is red on a stale 2-tuple unpack
  since `8e1b3a5`; fix the test (the product code is right), and from now on run the
  suite whole, not file by file.
- **N-1** — the "no `#` prefix" chat bug is true but its stated root cause is not; file
  it as an investigation, not a fix for a hash parse.
- **N-2** — `_bind_planner_script` on the legacy path: confirmed real, pre-existing,
  wider than reported (L3 refusals fall through to the legacy step path by design;
  `_check_task_board` has no flag guard).

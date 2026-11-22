# 0eea399: a waiting script keeps its binding; script plans need no subtasks — PASS with one required fix

Rev reviewed: `0eea399`. Reviewer: minecraft-reviewer@minecraft. 2026-11-22.
Fixes two defects from the step-4 live run (TEST 12:28Z plan-rejected; TEST 12:28Z wait-delivered-as-error).

## Verdict

PASS on the behaviour, with **one required fix before this ships**: the commit leaves
`test_script_tick.test_a_failed_tick_that_reported_holds_its_result_as_failure` red.
The code is right and the test is stale — but a red suite is not a PASS-able state.

Method: I built my own clean worktree at `0eea399` (`/tmp/rev4`, detached, no local
mods) rather than reading the builder's tree, and ran everything there.

## The one defect: a stale expectation the commit did not update

Full agent suite, discovered from clean:

| tree | result |
|---|---|
| `0eea399~1` (parent) | `Ran 666`, `failures=30, errors=1, skipped=1` |
| `0eea399` (this rev) | `Ran 674`, `failures=31, errors=1, skipped=1` |

28 failure names are identical in both trees, plus the known `ERROR: dashboard`
— pre-existing, unrelated. **Exactly one failure is new:**

```
FAIL: test_a_failed_tick_that_reported_holds_its_result_as_failure
AssertionError: {... 'ok': False, 'error': True} != {... 'ok': False}
```

The test asserts the exact dict a throwing tick stores in `last_result`. The commit
added `"error": True` to that dict (`script_tick.py:592`) — correctly, it is what
makes check 3 work — and did not update this expectation. The test's own comment
says why the field must be there: *"a no-verdict result is treated as `done`
downstream"*. So the test predates the field it now contradicts.

I verified the code, not just the test, by adding `"error": True` to the expectation
and re-running that file: `Ran 62 tests`, `OK`. The failure is the expectation, not
the behaviour.

`test_script_tick.py` is **not in the commit's stat**, which is how this survived:
the author ran the three suites their diff touched (173 tests, all pass — exact
count reproduced) and did not run the suite their change breaks. That is the same
shape as the two fixtures they caught and fixed; a third instance went the other way.

## Check 1 — spec delta matches code, nothing removed

- `openspec validate coded-agents --strict` → **"Change 'coded-agents' is valid"**.
- Delta header is **`## ADDED Requirements` only** — no MODIFIED, no REMOVED. Nothing
  spec'd was removed or reworded away.
- Four new requirements, 9 scenarios; each maps to a branch I drove below.

## Check 2 — a WAITING script is still bounded

This was the deepest question. The exemption is `_reported_a_wait` (agent.py:210),
and its placement decides whether a wait becomes unkillable. I read the tick in order:

- **Stop.** `_get_script_tick` returns `None` when `_script_halted_for_stop` is set
  (agent.py:4379) — so a stop gates **before** any tick exists. The wait exemption is
  downstream of it and can never be reached while halted.
- **Goal-generation staleness.** `_goal_generation_is_stale` is checked at the
  re-plan path (agent.py:4318) and refuses to bind work a stop superseded.
- **Idle bound.** Intact for a *silent* script: `_note_script_idle_tick()` → yield at
  `SCRIPT_IDLE_MAX = 5`. The exemption resets the run **only** for an explicit
  boolean `done: false`, so silence still bounds.
- **Daily code-hour cap.** Enforced **mod-side** (Java), not in this diff. The spec
  meters wall-clock while a script is *active*; a waiting script ticks every tick, so
  it accrues. I did **not** verify the Java enforcement — it is outside this commit
  and I did not read it at a rev. Stated as a limit below.

One thing I checked because it would make a wait unkillable in a different way: an
ACTIVE directive still counts separately via `_script_active_run` and the
`_directive_max_ticks` bound, and that block runs **before** the wait exemption — so
a wait that is really a stuck GOTO is still bounded. The exemption does not swallow it.

On "must all still end it": a player's stop **halts** the script (dispatch stops, the
binding is kept) rather than unbinding it — `_halt_script_for_stop`, which is
pre-existing (`1e2a789`), not introduced here. That is the spec's own hold/stop
distinction and is consistent, so not a defect in this change; noted so nobody reads
"kept binding" as a regression.

## Check 3 — a real throw / non-ok status still delivers error and unbinds

`error: True` is set in exactly one place (`script_tick.py:592`), the runner-error
branch — the comment there is correct that it is the only path where the runtime
observed a failure. A throw the agent catches logs `tick error, using planner` and
returns `False`, so the planner runs (agent.py:3897). Neither real-failure shape is
classified as a wait. Driven by mutant M2 below.

## Check 4 — a plain-text (no-verdict) result keeps its old `done`

`_hold_script_result` sends `verdict is None` to the `else: trigger = "done"` branch.
`test_a_result_with_no_verdict_keeps_the_old_done_trigger` asserts `trigger == "done"`
explicitly, and — the good part — feeds the text `"Failed: no diamond_ore found"`,
so it tests the actual trap: a plain string containing "failed" must not become an
error. Reddened by mutant M2, so it is load-bearing.

## Check 5 — the validator is narrowed, not relaxed

Bidirectional, and this is the check I trusted least until I mutated both directions:

| mutant | what it removes | reddens |
|---|---|---|
| **M3** | script plans may have no subtasks (`if script_plan: return` → `if False`) | `test_a_script_plan_with_no_subtasks_is_accepted`, `test_a_fenced_script_alone_signals_a_script_plan` |
| **M4** | the "is this a script plan" test (`_signals_a_script(d)` → `True`) | `test_a_step_plan_with_no_subtasks_is_still_rejected` |

M4 is the one that matters: it makes the rule permissive and **only** the
"step plan still rejected" test catches it. So the narrowing is genuinely tested from
both sides — a non-script plan with no subtasks still fails, while a script plan passes.

The code also does the subtler right thing: a *present but malformed* `subtasks`
(e.g. a string) is refused even for a script plan, so only absent/empty is excused.

## Check 6 — one instruction in the rendered prompt

Rendered `render_plan_prompt('Mystic', '3x3', offered=True)` and inspected the output
(8053 chars):

- `"append a fenced script block"` → **absent** (the old contradicting instruction is gone).
- Two passages say do-not-write (prose `:296`, schema `:338`) — both the same direction.
- `"wants_script": true` present in both.

No passage instructs the model to write the script in the reply, so the scenario's
"must not instruct both" holds.

## Check 7 — tests run and a mutant reproduced red

From a clean tree at the rev, bounded and niced:

- `test_agent_script_branch test_script_mode_gate test_result_delivery` →
  **`Ran 173 tests`, `OK`, `RC=0`**. The builder's 173 is exact.
- **M1** (kill the wait exemption: `if _reported_a_wait(...)` → `if False`) →
  `RC=1`, `failures=1`, and the reddened test is the right one:
  `test_a_script_that_reports_a_wait_is_never_yielded`.
- **M2** (`elif verdict is False` → `elif verdict is None`, i.e. a wait delivered as
  done) → `RC=1`, 6 red, including `test_a_reported_wait_is_not_a_reported_failure`.
- **M3**, **M4** as tabled above.

Each mutant was applied behind an `assert old in s`, parsed with `ast.parse` before
the run, and restored with `cmp` to confirm the bytes went back.

## Not established

- The **daily code-hour cap** is mod-side and I did not read its enforcement at any
  rev; I confirmed only that the agent-side exemption does not stop the script being
  *active* every tick (which is what the cap meters). Whether the Java cap ends a
  waiting script is verified by neither the code I read nor its tests.
- Nothing was executed on a live server. The two live defects this fixes were
  reproduced by the lead on TEST/PROD; I reproduced the *mechanisms* in unit tests
  and mutants, not the live run.
- `0eea399` is on `ship-ca27-harness`, not main, and is not deployed. The lead builds
  a test agent image and does the live run before prod.

## Required before ship

Update the stale expectation in `agent/test_script_tick.py` to include
`"error": True`, and re-run `test_script_tick` plus the full discover to confirm
`674` with the same single pre-existing error. I verified that this one edit makes
the file green (`Ran 62`, `OK`) — but the fix belongs in the commit, not in my
worktree.

## Note on my own instruments

Three probes this session addressed the wrong target and each would have read as a
defect. Recorded so a later reader does not inherit them:

- `grep` for a runtime string in `agent.py` when it lives in `planner.py` — nearly
  filed "the deployed image is not the claimed rev".
- `bots[k]['position']` when it is `bots[k]['status']['position']` — read `None` as
  missing data.
- Port `7433` when the runner is on `8080/8081` — carried into my own earlier step-1
  report as a wrong figure.

---

## Follow-up: `1073535`, and two corrections from the builder

Reviewed `1073535` ("the carried-error expectation includes `error: True`"), which
closes the one required fix. Verified in my own clean worktree, not the builder's.

### The fix is right, and it is expectation-only

- `git show 1073535 --stat`: one file, `agent/test_script_tick.py`, +11/-3. **No
  production file.** Production behaviour untouched, which is what was asked.
- `test_script_tick`: `Ran 62`, `OK`, rc=0.
- **Mutant (the builder's own claim, reproduced):** delete `"error": True` from the
  expectation → `Ran 62`, `FAILED (failures=1)`. The assertion is load-bearing.
- **Full suite, this rev:** `Ran 674`, `FAILED (failures=30, errors=1, skipped=1)`.
- **Full suite, parent `0eea399~1`:** `Ran 666`, `FAILED (failures=30, errors=1, skipped=1)`.
- **Failure sets diffed by name: 31 lines each, `IDENTICAL_FAILURE_SET`.** The one new
  failure is gone; nothing was introduced. (My first attempt at this diff compared
  against a baseline file I had already deleted, so it printed the whole set as
  additions. Rebuilt the baseline at the parent rev before reading the result.)

### Correction to my own review: the code-hours cap

I wrote that a waiting script "should still bite" the cap and filed the Java
enforcement as unverified. The builder read the source and is right; I am wrong
on both edges, and this amends the section above rather than standing beside it.

- **There is no Java metering.** 176 files under `src/main` (the builder said 177;
  the count here is 176 — immaterial, and I am recording my own number), zero hits
  for `3600` / `SECONDS_PER_HOUR` / `MS_PER_HOUR` / `code.?hour` in any of them.
- **The unit is ticks, not actions.** `openspec/changes/coded-agents/specs/bot-coded-agents/spec.md:419`
  — "The cap counts ticks… an active script that is simply not ticked accrues
  nothing"; `:440` — "Metering MUST run in the first release, even while the daily
  cap is unlimited". (The builder cited `:507-511` and `:528`; those are the Script
  Swap and Unreachable Runner requirements. Their quoted wording is real, at `:419`
  and `:440`. Line drift, not a false claim.)
- **A waiting script is ticked.** The `done:false` branch returns before
  `_result_slot.store` (`agent.py:3608-3611`), but `handled` is still True, so
  `_run_script_tick` returns True and the loop waits `TICK_DELAY` (=2.0 s) at
  `agent.py:4444` like any other pass. It saves planner calls and delivery slots,
  **not code hours**.

So the exemption does not make a waiting script free, which is what I suspected, but
my reason for thinking so was wrong: I had not read the unit, and "actions
dispatched" is not what the cap counts. Whether waiting *should* be free is a spec
question nobody asked me, and I am not raising it as a defect — `0eea399` behaves
consistently with spec `:419` as written.

The real gap the builder surfaced is upstream of this change: spec `:128` sets the
daily cap and `:440` requires metering in v1, and **no metering exists at any rev.**
That is a defect in the spec's own terms and belongs on a row; it is not `0eea399`'s,
and it does not change this verdict.

### A test name that states the old semantics (builder's point, agreed)

`test_script_tick.py:905 test_done_false_is_a_failure` — after `0eea399`, `False`
from `result_verdict` means *still working*, not *failed*. The assertion
(`assertIs(..., False)`) and the KILLS comment ("treating any result as done — the
goal closes and the bot stops with the work unfinished") are both still correct.
Only the **name** carries the pre-`0eea399` reading. The builder declined to rename
because renaming changes what that mutant claims to kill, and a fix commit is the
wrong place for it. Agreed — recorded here so the next reader does not take the name
for the semantics.

## Verdict, restated

**PASS.** `0eea399` is behaviourally correct and `1073535` closes its one defect
without touching production code. The bounded-exit exemption, the error/wait
distinction, the narrowed subtask rule, and the prompt fix all held under mutants.
The one red test was real, is now green, and the suite is back to its parent
baseline. The code-hours gap is pre-existing, spec-level, and untracked on any row.

# 07d21bd: three PTC prod script-bind fixes — PASS

Rev reviewed: `07d21bd` (`1073535..07d21bd`: `2770f32`, `6c9255b`, `8017888`, `07d21bd`).
Reviewer: minecraft-reviewer@minecraft. 2026-11-22.
Source row: `qitem-20261122130149-0ab60005621b4d92` (three prod Mystic bugs, 12:55-13:00Z).

## Verdict

**PASS.** All three ADDED requirements are implemented as specified, each is covered by a
test that reddens on a mutant of the exact behaviour it claims, and no spec'd behaviour was
removed. Suite green; full-suite failure set has **no new entries** against the parent.

## 1. Dry-tick bound: structural, and the live bound is protected

`script_client.py:263` selects `bound = DRY_TICK_TIMEOUT if dry else SCRIPT_TIMEOUT`.
`DRY_TICK_TIMEOUT = 2.0` (`:122`), `SCRIPT_TIMEOUT = 0.3` (`:109`).

The split is structural rather than a parameter:

- `call_runner(api, bot_state, *, post=None, dry=False)` has **no `timeout` parameter**. A
  caller cannot pass a number; it can only choose which of two named constants applies.
- `dry=True` appears at exactly **one production site**, `agent.py:3976` (the bind-time dry
  tick). Every other occurrence in the tree is a test. Verified by
  `git grep 'dry=True\|dry=False' 07d21bd -- agent/`.
- The flag reaches `call_runner` by one line: `script_tick.py:550`
  `call_runner(self._api, body, post=poster, dry=self._dry)`.

Mutants (each applied behind an `assert old in s`, restored and `cmp`-checked):

| mutant | reddens |
|---|---|
| `bound = SCRIPT_TIMEOUT` (collapse the split) | `test_a_dry_tick_uses_the_longer_bound` |
| `bound = DRY_TICK_TIMEOUT` (widen live too) | `test_a_live_tick_keeps_the_short_bound` + 4 others |

The second is the spec's explicit prohibition — "the dry bound does not extend the live
tick's patience" — and it bites.

**Does a 2 s dry tick block the loop?** Yes: `_bind_planner_script` calls `st.tick()`
synchronously on the calling thread, so the bind can block for up to 2 s. `TICK_DELAY` is
2.0 (`config.py:103`), so the worst case is one skipped loop pass. The bind happens once,
at a goal boundary, on the orchestrator thread. Acceptable: it replaces a path that
discarded a whole goal on a cold sandbox.

## 2. Task fill: scoped to script replies, filled from the caller's own goal

`plan_schema.py`: `script_plan = _signals_a_script(d)`, then
`if "task" not in d: if script_plan and goal: d["task"] = goal`.

**Can it leak a wrong task?** No — the value is the caller's `task`, not a model-supplied
one. `l3_planner.py:596` is the single production call site and passes `goal=task`, and
`plan = Plan(task=data["task"])` at `:614` reads the filled value back. The in-place
mutation of `d` is deliberate and commented: a fill that satisfied only the validator
would validate and `KeyError` one line later.

**Step-list replies keep the full contract.** The relaxation is scoped twice: the `task`
fill needs `script_plan`, and the `subtasks` excuse needs `script_plan` and still raises on
a *present malformed* value (`subtasks` not in `(None, [])`). Driven directly:

| input | outcome |
|---|---|
| step-list reply, no `task` | rejected: `plan missing required field: task` |
| `wants_script`, no `task`, goal given | accepted, `task == "tell me when it gets dark"` |

Mutant `if goal:` (fill for every reply) reddens
`test_a_step_list_reply_with_no_task_is_still_rejected`.

## 3. False success: a refused bind with no steps now fails the goal

`plan_orchestrator.py:398` — `if planner_script and not plan.subtasks:` sets
`status="failed"`, `meta["script_bind_refused"]=True`, and a reason string. It sits **after**
the handed-over return and **after** the "goal not handed to its script" log, and **before**
phase 2, so a refused bind *with* steps still falls through to the step list.

**How is a refused bind told apart from a real completion?** By plan state, not by a
message: `planner_script` truthy (the reply carried a script) and `plan.subtasks` empty
(nothing to run). The old bug was that this combination fell into phase 2, where
`current_subtask() is None` on the first pass set `complete`. The guard now intercepts
exactly that shape and returns before phase 2.

**The chat line is correctly scoped.** `agent.py:2175` sends it inside
`if not self.subtasks:`, in the same branch that returns `False` from `on_script`. With
steps present, the chat is skipped and phase 2 runs the steps.

| mutant | reddens |
|---|---|
| guard `if False and planner_script and not plan.subtasks` | `test_a_refused_bind_with_no_steps_fails_not_completes` |
| chat `if True:` (fire even with steps) | `test_a_refused_bind_with_steps_stays_quiet` |

## Tests: run myself, in a clean tree

Worktree `/tmp/rev7` at `07d21bd`, detached, `git status --porcelain` empty.

| suite | result |
|---|---|
| `test_script_client` | Ran 17, OK |
| `test_planner_script_output` | Ran 19, OK |
| `test_script_tick` | Ran 62, OK |
| `test_script_mode_gate` | Ran 27, OK |
| `test_script_prompt_kinds` | Ran 20, OK |
| `test_goal_generation_stop` | Ran 13, OK |
| `test_l3_script_path` | Ran 94, OK |
| `test_agent_script_branch` | Ran 141, OK |

Full `discover` at the rev: `Ran 685`, `failures=30, errors=1, skipped=1`.
Parent `07d21bd~5` (`0eea399`): `Ran 674`, `failures=31, errors=1, skipped=1`.

**Failure sets diffed by name: zero new, one fixed**
(`test_a_failed_tick_that_reported_holds_its_result_as_failure`, which `1073535` corrected).
The builder's "red set = 07:28Z baseline" claim holds.

`openspec validate ai-written-scripts --strict` → valid.

## Note on my own instrument

`test_plan_schema.py` and `test_plan_orchestrator.py` **do not exist**; I guessed both names
and each reported `Ran 1 test, FAILED (errors=1)`, which is an import failure wearing a
test result's clothes. The real homes are `test_planner_script_output.py` and
`test_script_mode_gate.py`.

Worse: my first run of mutant M4 (fill `task` for every reply) reported **OK, 113 tests**
and I nearly filed a coverage gap. The mutant survived because I ran it against
`test_planner_script_output` and `test_l3_script_path` only —
`test_a_step_list_reply_with_no_task_is_still_rejected` lives in `test_script_mode_gate`,
which I had not loaded. Rerun against the owning suite, M4 reddens exactly that test. A
mutant that survives when it must not is a dead harness, not a gap in the code.

## Not established

- No cluster actions; nothing here was exercised against the runner or prod. The 2 s bound
  is verified as *selected*, not as *sufficient* for a cold sandbox — the fix's premise is
  the prod dry tick exceeding 0.3 s, which I take from the failure log, not a replay.
- The code-hours cap remains unimplemented (spec `:128` / `:440`); unaffected by this rev,
  already recorded against `0eea399`.

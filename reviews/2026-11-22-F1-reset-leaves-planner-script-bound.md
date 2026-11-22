# F-1: `reset()` leaves a planner script bound and runnable

Asked by minecraft-lead: which other goal-ending paths leave a planner script
bound? Read and driven at `1e2a789`. Reviewer: minecraft-reviewer@minecraft.
2026-11-22.

## The design fact that settles most of the inventory

A hold **pauses** a bound script. `_run_script_tick` consults `_script_hold`
at its top and returns `SCRIPT_HELD` before dispatching (`agent.py:3503-3506`),
so a held script neither ticks nor double-issues with the planner. It is
released by `_end_script_hold` on that goal's terminal outcome
(`agent.py:1744-1762`) and the script **resumes with its binding intact**.

That is deliberate — a player's deployed script must survive a goal — so the
literal question "does the old script keep ticking alongside the new goal?"
answers **no** for every path that begins a hold.

## Per-path inventory

| Path | State | Verdict |
|---|---|---|
| Chat stop shortcut (`agent.py:769-792`) | unbound | covered, `1e2a789` |
| Dashboard `/api/bots/{n}/stop` (`dashboard/server.py:376`) | unbound-by-process-death | not a leak, see below |
| `/api/command` (`dashboard/server.py:314`) | n/a — injects chat, it is a **new goal** | not a cancel route |
| Task-board release/reassign (`agent.py:816-827`) | bound, paused by the new goal's hold | covered by design |
| New player goal while bound (`agent.py:905`, `:1108`) | bound, paused | covered, driven |
| Bot-to-bot delegated task (`agent.py:846-850`) | bound, paused | covered by design |
| **`Agent.reset()` (`agent.py:550-575`)** | **bound, runnable** | **F-1 — gap** |

### The `/api/command` stop route the question named does not exist

- `agent.py:4629` is inside `_execute_one`, the in-script `api.*` dispatcher;
  `case "stop": api.stop(bot)` at `:4711-4712` stops a **mod directive**, not a pod.
- The real dashboard route is `POST /api/bots/{name}/stop`
  (`dashboard/server.py:376-390`). It calls `_api_module.stop(name)` and
  `cancel_directive(name)` only — the mod side — and never touches
  `_planner_script`.
- It is **not** a leak, because `BotRunner.stop()` (`agent.py:513-525`) sets
  `_stop_event` and **joins** the bot's loop thread. The whole bot terminates;
  a bound script dies with it. Unbound in effect, by process death rather than
  cleanup. No spec coverage, and none needed.

## F-1: `reset()` keeps the binding

`reset()` clears the plan, the goal fields, `_current_task_id`, and calls
`_clear_script_hold()` — but never calls `_unbind_planner_script()`, and never
touches `_planner_script`, `_script_tick`, `_script_loaded` or
`_script_halted_for_stop`.

Reachable from the loop's RESET signal (`agent.py:4217-4221`), not only tests.

Driven with the real method, suite stub recipe:

    BEFORE  bound=True  hold={'goal_id': 'g1'}  plan=['step1']
    AFTER   bound=True  hold=None               plan=[]
    STILL BOUND AFTER RESET = True

**Failure scenario.** A bot running a planner script receives RESET. Goal, plan
and hold are wiped; the script stays bound, `_script_halted_for_stop` is False,
`_script_tick` is populated. The next tick's `_script_hold` check finds `None`,
so the script dispatches again under no goal and no plan — the exact
"script keeps acting after its goal ended" shape `1e2a789` removed from stop,
still present on reset. It also defeats reset's stated purpose ("clear all
planning state, cancel directives, and stop actions"): actions resume on the
next tick.

**Why no test caught it.** No scenario covers reset. `1e2a789`'s own comment at
`:563` says reset "drops any script hold unconditionally" and stops there. The
hold is dropped; the script is not.

**Suggested fix.** Call `_unbind_planner_script()` in `reset()`, or set
`_script_halted_for_stop` for hand-written bindings so neither kind survives.
A reset is terminal, so unbinding is the honest reading of "all tasks cleared".

## Scoping

`reset()` and `_begin_script_hold` were **driven**. The task-board and
delegation answers are **code reads** and are marked as such above.

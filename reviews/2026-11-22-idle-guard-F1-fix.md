# F-1 fix (idle guard): PASS — both gates hold, and the undriven guard works

Rev reviewed: `7c92a43` (parent `9d1864c`).
Reviewer: minecraft-reviewer@minecraft. 2026-11-22.

**Verdict: PASS.** My F-1 is closed. The counter gate and the in-progress gate
are both in place, ordered correctly, and each pinned by a test that reds at its
own name. I also drove the two guards the builder declared undriven — both work,
and one of them is now driven evidence rather than a claim.

## F-1 closed: the goal-less path

Both gates read at `7c92a43`:

- `agent.py:3443` — `if self._directive_in_progress(st)`, **before** the idle
  counter, so a walk resets the run instead of advancing it.
- `agent.py:3462` — `if not self._has_active_goal(): return False`, after
  `_note_script_idle()` (so the idle line still prints) and **before**
  `_note_script_idle_tick()` (so nothing is counted).

Driven past the builder's own window, which is `SCRIPT_IDLE_MAX * 4` = 20 ticks;
I ran 100:

    GOAL-LESS ticks=100 orch_calls=0 idle_run=0 plan=['mine something']
              planner_script=True
    SAYS_UNFINISHED: False
    SAYS_NOT_YIELDING: False

That is every property I filed against: no yield, the live plan kept, the script
still bound, the counter never climbing, and neither false log line. The builder
went past my fix direction here — gating only the yield let the counter still
climb and reset, producing a "not yielding" line every 5 ticks, which is the same
unbounded repeat quieter. That reading is correct and the gate placement
prevents it.

## Mutants

Each restored `cmp`-identical; `git status --porcelain` empty afterwards.

| Removed | Red |
|---|---|
| goal gate → `if False:` at `:3462` | `test_a_goal_less_bot_does_not_yield_and_keeps_its_plan` ONLY |
| in-progress gate → `if False:` at `:3443` | `test_a_running_directive_is_not_idle` ONLY |

Both exactly their own name, 114 tests run. Suite at the rev, summary read
unpiped: `Ran 164 / OK`, `rc=0`. `openspec validate script-lookups-and-results
--strict` → valid, `rc=0`.

## The guards the builder said no test drives

Stated plainly, so this is not counted as their coverage but as mine:

**`_yield_script_to_planner`'s goal-less refusal (`:3856`).** Driven directly,
goal-less, as the repeat-spin caller can arrive:

    CALLEE goal-less: plan=['mine something'] planner_script=True
                      idle_run=0 orch=0
    LINES: ['not yielding (spin: the same action completed N times in a row): no active goal']

It refuses, keeps the plan, keeps the script bound, and says why. Behaviour
verified; still no test.

**The reset at `:1758`.** The builder dropped a scenario rather than assert it
untested. I agree with the call and did not drive it either — noting it as an
agreed gap, not a finding.

## Cites

Every one resolved at `7c92a43`, not at HEAD:

- `agent.py:3462` → `if not self._has_active_goal():`
- `agent.py:3443` → `if self._directive_in_progress(st):`
- `script_tick.py:471` → `self.last_task = envelope.get("task")`
- `Directive.java:22` → `private DirectiveStatus status = DirectiveStatus.ACTIVE;`

`DirectiveStatus` has exactly four members (`ACTIVE, COMPLETED, FAILED,
CANCELLED`) and `Directive.toMap()` emits `status.name()` at `:63`, so the
Python's `== "ACTIVE"` compares against the literal string the wire carries.
The predicate is exact.

## N-1 (scoped note, not a blocker): `ACTIVE`-forever suppresses the bound

The in-progress gate is new in this commit, so it introduces a hole: a behaviour
that never terminates leaves the directive `ACTIVE`, and the idle bound can then
never fire. `Behavior` is an interface — each behaviour implements `tick`
independently and there is no inherited tick bound (34 of the 40 behaviour
classes have no `MAX_TICKS`/timeout of their own).

I judge this acceptable and better than the alternative, which is why it is a
note and not a finding. Pre-fix, a legitimate long `FOLLOW` hit the bound after 5
ticks and had its goal torn down every 5 ticks, script unbound and `_plan_steps`
cleared — a working follow destroyed on a timer. The gates trade a rare hang for
a common false positive. And the long-running behaviours that matter are bounded
at the mod layer anyway: `GotoBehavior.MAX_TICKS = 600`, and
`FollowBehavior.OFFLINE_GIVEUP_TICKS = 400`.

Worth a follow-up when something like `FOLLOW` on a present player can hold a
goal indefinitely: either give the idle guard a much longer absolute backstop, or
bound the behaviour. Not owed by this commit.

## Not established

No run against a live bot. Trial 4.3's end-to-end remains unobserved: this makes
a script able to poll a long walk without being yielded, which is a precondition
for observing it, not the observation.

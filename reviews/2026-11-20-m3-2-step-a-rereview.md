# Review — M3-2 step (a): planner emits a script, agent binds it in memory (re-review)

**Verdict: PASS**
Revs: neoforge `6f9306b` (code + tests), `6137284` (citation re-resolve).
Runner unchanged at `549c80d` (previously passed).
Reviewer: minecraft-reviewer. Date: 2026-11-20.

This re-review closes the three findings filed against `0c232fa`
(`reviews/2026-11-20-m3-2-step-a.md`). All three are fixed and each fix is
killed by a mutant I ran myself.

## F1 — the latch reset had no test (was BLOCKING) — CLOSED

At `0c232fa` I deleted both reset lines in `_bind_planner_script` and all 314
tests passed: the old assertion at `test_agent_script_branch.py:1049` read a
value `setUp` had just written, so it could not distinguish a reset from a
no-op.

At `6f9306b`, `test_binding_clears_a_previously_latched_tick` starts the bot
**latched** (`_script_tick = stale`, `_script_loaded = True`) — the real case —
binds, and asserts the next `_get_script_tick()` is not the stale object.

Mutants I ran (56-test changed-module set, `agent/agent.py:3189-3190`):

| mutant | result |
|---|---|
| delete both reset lines | rc=1, FAILS `test_binding_clears_a_previously_latched_tick` |
| clear `_script_tick` only, leave `_script_loaded=True` | rc=1, FAILS the same test |

The second is a half-reset the builder did not claim, and the test catches it.

## F2 — taskboard caller silently dropped a script answer — CLOSED

`agent.py:1702` (now `:1707`) treated a script answer as an empty plan:
`_plan_steps = []`, "Plan (0 steps)", silent idle. The fix carries the same
guard as the `:904` caller.

Mutant: delete the guard at `:1707-1709` → rc=1, FAILS
`test_a_taskboard_script_answer_is_bound_not_silently_dropped`. Restored,
`cmp` identical.

Note on the two call sites: the `:904` caller calls `_consume_message(msg)`
before returning; the taskboard caller has no message, so the asymmetry is
justified, not an omission.

## F3 — two stale citations — CLOSED, and the fix re-moved others

`agent.py:1330-1333` (a docstring) → `:1349-1352` (`self._script_hold = {`).
`agent.py:2901-2904` (a docstring) → `:2927-2930`.

Adding the F2 guard shifted everything below `:1702` by +7, staling six more
addresses. The builder re-resolved all of them at `6137284`.

I checked **every** citation in the change at `6137284` by **line text**, not
by number:

- `agent.py:235` → `self._script_loaded = False`
- `agent.py:1349-1352` → `self._script_hold = {` … `}`
- `agent.py:3118` → `scripts_dir = (_os.getenv("SCRIPTS_DIR") or "").strip()`
- `agent.py:3139` → `name = bindings.get(self.name)`
- `agent.py:3213-3215` → `if self._script_loaded:` … `self._script_loaded = True`
  (the one-shot latch; `tasks.md:37` and `spec.md:99` both correctly cite it)
- `agent.py:2916` → `st = self._get_script_tick()` — confirmed the **only**
  production caller by grep
- `agent.py:3070-3147` → opens `_bound_script_path`, ends at its `return`
- `binding.js:31,44,45-52,59-65,126-136,154-174,244-251,314,337-346` — all
  resolve at `549c80d`; `binding.js` is byte-identical between `549c80d` and
  current runner HEAD, so the later `worker.js` churn does not stale them.

`openspec validate ai-written-scripts --strict` → valid, rc=0.

## Test tallies

- Changed modules (`test_agent_script_branch` + `test_planner_script_output`):
  **56 tests, OK**, rc=0.
- Full suite: **316 tests, 30 failures + 1 error** — identical to the
  pre-existing set at `0c232fa`. I diffed the failure-name sets at both revs:
  **identical**. The reds are `test_scout_script` (30) and the `dashboard`/
  `uvicorn` import error (1); none touch this change.

The earlier "93 vs 54" was module-boundary disagreement, not an arithmetic
error: 93 = branch + script_tick + planner. Neither figure was wrong; the
builder now names the set.

## Notes carried forward

- Ordering for the dry tick is pinned by the `dry.called` assertion, not only
  by the outcome — a bind that runs before the dry tick still reddens.
- The runner's `src/` moved after `549c80d` (`worker.js`), so a future change
  re-citing `binding.js` must re-check against that rev's content, not
  `549c80d`.

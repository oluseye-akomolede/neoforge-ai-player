# NOT PASS — failure verdict re-plans, but a throw-tick result with no `done` still closes the goal

Rev reviewed: `8f7dfbe` (agent). Reviewer: minecraft-reviewer@minecraft. 2026-11-22.

The classification fix is correct and well tested. One finding (F-1) blocks: the
second requirement this same commit adds is not satisfied by the code it adds,
and the gap is the exact stranding the commit set out to fix.

## What passes

- **The root cause is real and fixed.** `_hold_script_result` hard-coded the
  `"done"` trigger (`agent.py:3384`); it now reads `result.get("ok")` and stores
  `"error"` when the script said `{done: false}`. `_maybe_plan_on_result` sends
  `error` down the `may_call` → `_plan_with_result` path and never reaches
  `_close_result_goal`.
- **`None` is correctly not success.** A plain string, a non-object, a
  non-boolean `done` and truncated text all keep the old `"done"` trigger, so
  no existing script changes behaviour. Verified: `'{"done": true}'` → `True`,
  `'{"done": false}'` → `False`, `'{"found": 3}'` → `None`.
- **Full suite at the rev:** 481 tests, OK (skipped=1), 19 modules, rc read
  unpiped.
- **Mutant A** (hard-code `trigger = "done"`): exactly 1 failure, its own name
  (`test_the_verdict_decides_the_trigger_the_slot_receives`).
- **Mutant B** (`result_verdict` always `None`): 4 failures, all named, matching
  the builder's claim. Both files restored `cmp`-identical.
- `openspec validate script-lookups-and-results --strict` rc=0, unpiped.
- **Driven, not asserted:** five consecutive `{done: false}` results give 4
  planner calls then `held (hour-cap)` with the result still pending and no
  `system_chat`. The caps bound the failure path, and a failing script never
  tells the player it succeeded.
- The `.upper()` survivor I raised on `37fe55d` is now documented in the
  docstring, with a better justification than mine for why it is not dead.

## F-1 — a result carried by an error tick closes its goal as done

This commit adds **two** requirements. The second, "A Failed Tick's Result Must
Not Be Silently Dropped", says a script that calls `api.result` and then throws
must keep that result *and* have it "treated as a failure result, not a done
one". The first half is satisfied — `_hold_script_result` at `agent.py:3485`
runs before the `not handled` return, so the result is held. The second half
is not.

`result_verdict` classifies on the script's `done` field, and on a throw-tick
the script threw before setting it. So the verdict is `None`, and the trigger
line is

    trigger = "done" if verdict is None else ("done" if verdict else "error")

which maps `None` to `"done"`. A `done` result **closes** its goal. Driven
end to end through the real `_hold_script_result` and
`_maybe_plan_on_result`, with `{"text": "partial scan, 3 blocks", "ok": None}`
(the runner's `status: error` shape carrying `result`):

    TRIGGER_FOR_NOVERDICT='done'
    THREAD_CALLS=0 CHAT_CALLS=1
    GOAL_ID_AFTER=''

No planner call, one green `system_chat`, goal id cleared. That is the lead's
05:15Z report reproduced on the path this commit's own requirement describes:
work stranded, player told it succeeded. The runner does its part — `main.js`
carries `result` on the error branch specifically so this case is not lost —
and the agent discards the classification.

**Why the tests miss it.** `test_runner_error_status_falls_through` asserts
only `handled` and `actions`; it never checks that a carried result reaches the
slot or what trigger it gets. The new tests seed `"ok": False` and `"ok": None`
directly, so neither exercises a real error tick carrying a verdictless result.

**Suggested fix.** On an error tick the status is itself the verdict: a result
arriving with `status: error` is a failure whatever its `done` field says. The
cleanest shape is for the tick to pass its status into the hold — e.g.
`_hold_script_result(result, failed=<status is error>)` — and have the trigger
be `"error"` when `failed` is true, falling back to `verdict` otherwise. That
keeps the no-verdict-means-done rule for ordinary (non-error) ticks, which is
what the backward-compatibility argument is about, and stops it from
overwriting the one case the requirement names.

## N-1 — pre-existing, not owed here

`escalate` is documented as a trigger (`result_delivery.py:4`,
`planner.py:66`) but no producer ever stores it; the only writers are tests.
It is handled as non-`done`, so it re-plans rather than closing, which is
benign. Noted only so the docstring's list is not read as a live contract.

## Not established

- No live bot. That a real script reports `{done: false}` depends on the script
  author; nothing here observes one.

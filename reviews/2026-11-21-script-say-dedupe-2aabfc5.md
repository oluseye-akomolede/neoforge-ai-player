# Review: script-say-dedupe implementation 2aabfc5

Change: `openspec/changes/script-say-dedupe`, delta approved at `d74b49a`.
Row: `qitem-20261121202425-4944c8b2371836f3`.

## Verdict

PASS with one correction (F-1) and one answer I would reverse (F-2). Neither blocks the change; F-1 changes what the planner is told, F-2 changes one return value on a path the change itself is about.

## What I ran

- Affected suites against `2aabfc5` in the builder's worktree: `python3 -B -m unittest test_script_say_guard test_agent_script_branch test_script_tick test_l3_script_path` -> **Ran 231, OK**.
- Mutants, `python3 -B`, `agent.py` restored with `cmp` after each:
  - **M-A** `if _suppressed:` -> `if False and _suppressed:` (suppressed-only is not handled) -> **red, 1 failure**. So `test_a_suppressed_only_tick_is_still_handled` is not green on a constant.
  - **M-B** `if _suppressed:` -> `if True:` (return True unconditionally) -> **red, 4 failures**. The neighbouring idle tests catch the over-broad shape.
  - **M-C** add `self._script_say_guard = ScriptSayGuard()` to `reset()` -> **red, 1 failure**. So the `inspect.getsource` test does bite on the property it names.

## Answers to the questions asked

**(a) Is `test_a_suppressed_only_tick_is_still_handled` driving production?** Yes. It injects a real `ScriptTick` via `_real_tick(self._wire(actions=[...]))`, so `translate_runner_actions` splits the `say` record out and `ScriptTick.tick` returns `handled=True, actions=[]` with one delivery. The fake runner truly returns no `actions`. Through the production path, `_suppressed` is the only thing standing between that tick and `return False`, and M-A reds it. Good test.

**(b) Is `inspect.getsource(reset)` too weak?** Not for the property it names, and I would not build the full fixture. It fails on the mutant it claims to kill (M-C) and on the realistic regression ("reset() also clears the guard"). What it cannot see is a reset that delegating to a helper which clears the guard; I would leave that alone — a full fixture for an `__new__` class would end up testing the fixture, exactly as the comment says.

**(c) `return True` on suppressed-only vs the idle path — keep it, and F-2 is where it goes wrong.** I agree with `True` here. A suppressed repeat means the script produced output and the tick was handled; `return False` is the "did not run, planner may" fallback this change exists to avoid, and the 2026-11-20 shape is exactly that.

## F-1 (correction): the planner is told to "say only when something changes", which moves work into the agent's memory

`planner.SCRIPT_SURFACE` gained a line telling the planner to speak only when something changes. But dedupe is now enforced per line **content** for 60 s, and a script's own `api.remember`/`api.recall` is the only place it has memory of what it said. A script that reports `"100 -> 120 iron"` each tick is not saying the *same* line, so the guard does not suppress it and the planner gets no help from the new line; what actually stops the repeat is the agent. That part is fine.

What is not fine is the guidance as worded: it asks the planner to make the change-detection judgement at authoring time, and the acceptance test (task 4.x) is likely pinned to that string. If the planner obeys literally it produces `if (x !== api.recall()) api.say(...)` and then the guard never fires for that script — meaning the mutant "dedupe not consulted" is now unreachable for the majority of real scripts, and the change's own test `test_the_same_line_twice_is_delivered_once` only covers the literal-repeat path.

This is not a code defect. It is a **scope** statement: the guard is the backstop for scripts that repeat, not a mechanism that removes the need for a change check, and the prompt line should say that. Suggested wording (one clause, same line):

> Say only when something changed since the last tick; a line you say again within a minute is suppressed, so a repeat is wasted, not harmful.

If the builder keeps the current wording, the change is still correct but the spec delta should record that content dedupe is a backstop, not the intended mechanism for a status-report script.

## F-2 (correction): `True` when the script handled the tick through a real action and only the *remainder* was suppressed

Look at the branch again. `if _suppressed: return True` sits inside `if not actions:`, so it only fires when the script proposed nothing. That is right. But the case that is now unreachable and should not be is a tick with **no actions and a suppressed-only delivery while the script is held by a goal**: `SCRIPT_HELD` is checked before delivery, so a held goal short-circuits before `_suppressed` is ever computed. My M-C-adjacent check is: `hold` truthy -> `return SCRIPT_HELD`. In that state a repeated say is *not delivered* and the planner is told it ran. The comment at `agent.py:3176` says the player's goal "already spawned the planner", so the planner is not starved — but the bot's chat silence is now indistinguishable from "held and silent on purpose". That is a log-visibility question, not a correctness one: add the `held by goal ... not dispatching` line's suppression count, or accept it. **Not blocking**; recorded so it is a decision, not an oversight.

## F-3 (note, not a finding)

`guard._window` is read from `agent.py` for the log line. It is private by name only; the guard exposes no public accessor. Fine today, but if `ScriptSayGuard` ever moves behind the wire (a runner-side guard, say), that line silently prints the default. Consider `guard.window` — three characters and a property.

## Verified against the source, not the message

- `binding.js:257/:270` charge both calls through `accept()`/`acceptAction()` **before** any agent-side check, so suppression never refunds runner budget. This is the reason "not a rate limit" holds: the runner is still the counter.
- `worker.js:74` returns `state.actions`, and `translate_runner_actions` (`script_tick.py:189`) splits `say`/`send` out of that list. So a dry tick's `last_deliveries = []` really does drop the only channel a rehearsal could speak through, and the test's `_wire(actions=[...])` is the real wire shape.
- `script_tick.py:559` is the one place actions are split; there is no second channel.

## Not verified

- The agent-wide `Ran 475, FAILED (errors=1, dashboard ModuleNotFoundError: uvicorn)` — I ran the affected modules plus script_tick and l3_script_path (231, OK) and did not reproduce the dashboard error in that set. It is described as pre-existing; I did not confirm that on a baseline rev, so I am not certifying the full 475.
- I did not re-run the runner suite (179 pass) — the change touches no runner file.

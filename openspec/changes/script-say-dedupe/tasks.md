# Tasks — script say dedupe

## 1. The guard

- [ ] 1.1 Add `agent/script_say_guard.py` with `ScriptSayGuard(clock=time.monotonic, window_seconds=60.0)`: `check(call, text, to=None)` returning whether to deliver and whether this is a first suppression for the key in the window; `deliver(key)` recording the time. Docstring records why it lives per bot and survives `reset()`.
- [ ] 1.2 Tests for the guard alone with an injected clock: same key inside the window suppressed; at exactly 60.0 s delivered and at 59.999 s still suppressed (the comparison is `< 60.0`); different text delivered; different recipient delivered; alternating keys each suppressed after the first; the "first suppression in this window" flag true once then false.

## 2. Wiring into the delivery loop

- [ ] 2.1 Create the guard per bot beside `ResultSlot` (`agent/agent.py:277` region) so it survives `reset()`; confirm `reset()` does not clear it (test).
- [ ] 2.2 In `_deliver_script_deliveries` (`agent/agent.py:3019`) consult the guard before delivering; count suppressed separately and return both counts; log at most one suppression line per key per window.
- [ ] 2.3 Update the docstring at `agent/agent.py:3028-3031` to say the dedupe is content-dedupe, not a rate limit, and that the runner's cap is still the only rate bound.
- [ ] 2.4 A suppressed call still counts toward the tick having handled it, and is not reported as a refusal (test).
- [ ] 2.5 The call site at `agent/agent.py:3160` reports delivered and suppressed counts (log line).
- [ ] 2.6 A dry tick neither reads nor writes the memory (test), since it delivers nothing.

## 3. Prompt guidance

- [ ] 3.1 Add the "use `api.say` only when something changes; never post the same status every tick" line to `planner.SCRIPT_SURFACE`.
- [ ] 3.2 Test: both rendered prompts contain the guidance; both still contain no `{{` and no `}}` (the gate from `fd5416b` stays green with the line present). Count the braces in the output, do not eyeball.

## 4. Close out

- [ ] 4.1 Run the affected suites by discovery and quote totals: agent suite and runner suite. Name the known `dashboard`/`uvicorn` import error if it appears.
- [ ] 4.2 `openspec validate script-say-dedupe --strict`.
- [ ] 4.3 Mutants, `python3 -B`, one per test: window comparison removed; key ignores `to`; key ignores `text`; log per tick instead of per window; guard cleared on reset; brace gate.
- [ ] 4.4 Report the shas and the test counts copied from the output; file the reviewer row.

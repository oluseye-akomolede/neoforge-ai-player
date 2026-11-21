# Review — 5623e81, 631038d (F-4 spec rewording)

Rev: `631038d` on `ship-ca27-harness` (builder worktree `~/minecraft-wt-deepseek/neoforge-ai-player`).
Requested by minecraft-lead 2026-11-21 00:00Z.
Reviewer: minecraft-reviewer@minecraft.

## Verdict

**PASS on the rewording, with F-5 and F-6.** The spec now describes the code
truthfully: the 900 s cooldown is the binding limit, and the cap cannot refuse
anything the cooldown would not. `design.md` no longer makes the bind/release
argument. Two findings: one scenario is unfalsifiable (F-5), and the design's
"each independently sufficient" and the refusal log line both overstate the cap (F-6).

## What I checked, and how

Every number below came from running the shipped constants, not from reading
the prose.

### The three scenarios against `result_delivery.py`

`agent/result_delivery.py:25-26` holds `MAX_RESULTS_PER_HOUR = 4` and
`COOLDOWN_SECONDS = 15 * 60`; `agent/agent.py:277` constructs `ResultSlot()`
with both defaults, so production runs cooldown 900 s, cap 4.

**Attribution of refusals** (loop script, one tick a minute, 500 ticks,
production constants). At each instant I evaluated the cap test and the
cooldown test independently, then asked which is decisive:

```
cap&cd=424  cap-only=0  cd-only=42  neither=34
```

`cap-only == 0`: **the cap never refuses a call the cooldown would have
allowed.** Calls land at 0, 900, 1800, 2700, 3600 … — the cooldown alone
produces them. This confirms the lead's correction and my earlier statement in
`a0d4823`, for the right reason. The cap's higher *reported* refusal count is
branch order, not decisiveness: `may_call` (`result_delivery.py:74-79`) tests
`len(recent) >= self._max_per_hour` before the cooldown, so when both block it
names the cap.

**Rolling-hour maximum** (arrivals every 1 s, the worst cadence):
`calls=23 max-in-rolling-hour=4`. At 899 s gaps: `max=3`. At 60 s: `max=4`.
The specification's "at most four in any rolling hour" is measured, not assumed.

**The lead's 899 s question, settled.** Not a defect. A refused result stays in
the slot (`store` overwrites; nothing drops it), so two arrivals 899 s apart
collapse into one call 1798 s after the last — 13 s *late*, never early. The
comparison is strict in the correct direction: `result_delivery.py:76` uses
`<`, so a call is allowed at exactly 900 s and refused at 899.999 s.

### Falsifiability (mutants run in the suite's own shape)

All run from `agent/` as `python3 -m unittest`; the tests import flat module
names, so a run from the repo root errors on import — my first attempt did
exactly that (81 errors, 0 real signal). Baseline: 9 OK, 84 OK.

| Mutant | What it removes | Result |
|---|---|---|
| M1 `COOLDOWN_SECONDS = 1` | the 900 s spacing | 2 red: `test_the_fifteen_minute_cooldown_turns_it_red`, `test_the_four_a_hour_cap_turns_it_red` |
| M2 cooldown branch → `if False:` | the cooldown check entirely | 3 red: the two cooldown-held tests + `test_a_pending_result_is_held_off_inside_the_cooldown` |
| M3 `<` → `<=` | the boundary | 2 red: `test_after_the_cooldown_a_second_call_is_allowed`, `test_a_pending_result_is_held_off_at_the_hour_cap` |
| **M5 cooldown keyed per script** | bot-level keying (the new scenario's target) | **0 red, 84 green** |

### F-5 — "The cooldown is per bot, not per script" cannot fail

The scenario at `spec.md:129-133` exists to kill a cooldown keyed by script
rather than by bot. Nothing does. I built that mutant — it clears the call log
whenever the incoming trigger differs from the last, which is per-script
keying — and it produces **zero reds across 84 tests**.

The mutant is real, not inert: with a positive control it changes behaviour.

```
mutant,  trigger changed 60 s apart -> allowed: True
real code, trigger changed 60 s apart -> allowed: False
```

So the mutant opens a genuine bypass (a planner alternating `done` and `error`
scripts re-plans every minute), and no test notices.

The reason per-bot keying holds today is structural, not tested: `ResultSlot`
is a per-agent-instance attribute (`agent.py:277`), so one bot cannot share
state with another by construction. A scenario SHOULD still pin it, because
the structural fact is what a future refactor would break — a module-level
cache, a `lru_cache` on a helper, or a shared registry would all be per-process
without touching the spec.

The other 10 reds I first got from a shared-state mutant were same-slot tests
contaminated by the sharing, not two-bot comparisons. There is no two-bot test
anywhere (grepped `agent/` and `openspec/`: the phrase appears only in this
new scenario). Recommended fix: instantiate two agents with two slots, drive
both inside one 15-minute window, and assert each gets its call — that reds
under M5 and under the shared-state shape.

### F-6 — two places still overstate the cap (minor, fix at 04Z)

The builder flagged `design.md:462-466` as calling the cap the rate bound. It
does not use that phrase; it lists the cap **first** and heads the list with
"Three caps, **each independently sufficient** to stop a runaway"
(`design.md:460`). Under the shipped constants that heading is false for the
cap: it is never the decisive guard (`cap-only = 0` above). The *ordering* also
implies precedence. Suggest making the cooldown the first bullet and rewording
the heading to "three caps; the cooldown binds, the cap is a backstop".

The same overstatement reaches the log. `agent.py:1000-1002` prints
`held (hour-cap)` whenever the cap branch is reached first, which is the
overwhelming majority of refusals (424 of 466 in the probe) even though the
cooldown would have blocked the same call. During the trial, a grep for
`hour-cap` will therefore read as "the cap is binding" when it is not. If the
trial's drop counter or any log claim reads on that string, it will mislead.
Cheapest fix: when both guards block, name the cooldown (check it first), or
print both reasons.

This is not a code defect — `may_call` refusing is correct either way — but it
will corrupt the §4 trial's reading, which is the thing this change exists to
measure.

### 5623e81 / 631038d content

`5623e81` replaces the unreachable "ten distinct scripts" scenario with the
three now present, and correctly drops the claim that it proved per-bot keying
(the single-slot overwrite collapses ten results to one). `631038d` rewrites
`design.md:468-470` from bind/release reasoning to the cost argument, which
matches the spec. Neither changes code. `openspec validate
script-lookups-and-results --strict` → valid, rc=0, at `631038d`.

**On the stale scenario:** confirmed. `spec.md:158-166` now reads
`(DEFERRED)`, 3.9 is unticked, and the wording says the discard "starts
working once a tick reports the goal", which is true of the code as it stands.

## Suites

Run bounded, from `agent/`, at `631038d`:

- `test_result_delivery`: 9 OK
- `test_agent_script_branch`: 75 OK
- combined pair used for the mutants: 84 OK
- full discovery: 446 tests, 1 error — `dashboard` (the known environment
  breakage, `uvicorn`), none from this change.
- `openspec validate script-lookups-and-results --strict`: valid, rc=0.

No `ollama-l3` requests, no pod exec, nothing in `ci`.

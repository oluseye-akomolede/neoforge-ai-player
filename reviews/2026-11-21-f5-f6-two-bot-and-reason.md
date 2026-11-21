# Review — 6054f4f, abda00a, 38eb1c4 (F-5, F-6 closed)

Rev: `38eb1c4` on `ship-ca27-harness` (builder worktree `~/minecraft-wt-deepseek/neoforge-ai-player`).
Requested by minecraft-lead 2026-11-21 00:07Z.
Reviewer: minecraft-reviewer@minecraft.

## Verdict

**PASS.** F-5 and F-6 are both closed, and closed in the way my findings
described rather than by silencing them. Three commits, all three checks the
lead named pass, verified by running.

## (1) The two-bot test reds on MY mutant, not only the builder's

`6054f4f` adds `test_two_bots_each_get_a_call_inside_the_same_15_minutes`
(`test_agent_script_branch.py`). It builds two real `BotRunner`s via
`_bot()`, each with its own `ResultSlot` on one shared clock, and drives both
through `_run_planner_for_pass` a minute apart.

**My mutant from `2ae0cf3` still shows 87 green on it** — and that is my
mutant's shape, not a test defect. My mutant clears the call log when the
*trigger* differs; both bots in this fixture run the same script, so `trigger`
is `"done"` for both and the bucket is never cleared between them. It models a
per-trigger key, not a per-script-identity key. I verified that directly:
same trigger, 60 s later, my mutant still refuses — it is not exercised by a
same-script two-bot fixture at all.

The scenario names a cooldown keyed by **the script that produced the result**.
I built that mutant — a process-level bucket keyed by script identity, shared
across slots — and it **reds `test_two_bots_each_get_a_call_inside_the_same_15_minutes`**,
plus 11 others from the shared-state contamination the builder honestly
predicted.

To make sure the new test is not merely red-under-anything, I also ran a
**minimal** mutant in which the *only* defect is bot-keying (a process-wide
cooldown opened by the first call ever made, nothing else touched). It reds 4
tests and the two-bot test is among them:

```
RED test_two_bots_each_get_a_call_inside_the_same_15_minutes
RED test_the_goal_the_delivery_is_attributed_to_turns_it_red
RED test_the_reason_still_names_the_cap_when_only_the_cap_refuses
RED test_a_pending_result_is_held_off_inside_the_cooldown
Ran 78 tests ... FAILED (failures=4)
```

So the new test pins per-bot keying specifically, not just "something is
wrong." Check (1) passes.

## (2) abda00a changes only the reason, never the decision

This is the check that mattered most, because reordering guard clauses is
exactly the edit that can silently change a rate limit.

**Replayed my 500-tick attribution** (one tick a minute, production constants,
`ResultSlot()` at both revs) by loading `agent/result_delivery.py` from
`631038d` and from `38eb1c4` and running both:

```
OLD 631038d: {'allowed': 34, 'cooldown': 42, 'hour-cap': 424}
NEW 38eb1c4: {'allowed': 34, 'cooldown': 466}
allowed sequences identical: True | allowed count: 34 34
```

**The allowed set is byte-identical: 34 calls either way, same ticks.** The
only change is the label — 42 + 424 = 466, so every previously-misnamed
refusal now reads `cooldown`, and no `hour-cap` label remains at production
constants. That is precisely the intended effect and nothing else moved.

This also re-confirms F-4's premise on the new code: at 900 s the cap retires
from the log entirely, because it is never the decisive guard.

I independently checked the boolean is order-independent by evaluating the cap
and cooldown predicates separately and combining with `or` — the decision is
identical under both orderings, which is the structural reason a reorder is
safe here.

## (3) 449 = 446 + 3, one error, dashboard only

- New `def test_` lines added across the three commits: **3**
- `def test_` lines removed: **0**
- Discovery at `38eb1c4`: **Ran 449 tests, FAILED (errors=1)**, the single
  error being `dashboard` (the pre-existing `uvicorn` environment breakage).
- `test_result_delivery`: 9 OK. `test_agent_script_branch`: 78 OK (75 + 3).
- `openspec validate script-lookups-and-results --strict`: rc=0.

449 - 446 = 3, matching the three added tests, with no test lost.

## F-6 (38eb1c4) — closed

`design.md:461` now reads "Two bounds and one stop, **in order of what does
the work**", leads with "**The cooldown is the binding limit**", and gives the
cap its own bullet headed "**a backstop**", stating it "is reachable only if
the cooldown is shortened or removed". The "each independently sufficient"
claim is gone. This matches the measured behaviour.

`abda00a` fixes the log half in `result_delivery.py:74-84`: the cooldown is
checked first, with the reasoning recorded in a comment. The trial's grep for
`hour-cap` will now read correctly.

## Suites

Bounded, from `agent/`, at `38eb1c4`:

- discovery: 449 tests, 1 error (`dashboard`/`uvicorn`, pre-existing)
- `test_result_delivery`: 9 OK
- `test_agent_script_branch`: 78 OK
- `openspec validate ... --strict`: rc=0

Builder worktree left clean after mutant runs (`git status --short` empty at
`38eb1c4`). No `ollama-l3` requests, no pod exec, nothing in `ci`.

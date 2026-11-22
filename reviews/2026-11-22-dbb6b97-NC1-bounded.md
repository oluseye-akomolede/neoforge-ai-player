# NC-1 bounded: `dbb6b97` — PASS

Rev reviewed: `dbb6b97` (`agent/agent.py`, `agent/test_agent_script_branch.py`,
`openspec/changes/script-lookups-and-results/specs/bot-coded-agents/spec.md`).
Reviewer: minecraft-reviewer@minecraft. 2026-11-22.

**Verdict: PASS.** NC-1 is closed.

## What the fix does

A third terminal condition above the in-progress gate (`agent.py:3489-3498`):
count consecutive ticks with a directive `ACTIVE` **while a goal exists**, and
yield the goal at `SCRIPT_DIRECTIVE_MAX_TICKS = 3000` (`agent.py:136`).

The placement is the substance. The counter increments *above* the
`return False` that the pre-fix code used to skip the bound, which is what makes
the bound reachable at all. The goal-less branch resets and returns before the
counter (`:3486-3488`), preserving the trial-4.2-retry fix. The dispatch seed
(`:3549`) stops a productive script accruing to the bound.

## Verified at this rev

- Suite `test_agent_script_branch`: **120 tests, OK, rc=0** (read unpiped from
  the runner's own line).
- Mutant — bound disabled (`if False:`): reds exactly
  `test_a_directive_active_past_its_own_bound_yields_the_goal`. 1 failure, 120 run.
- Mutant — dispatch seed removed: reds exactly
  `test_a_dispatching_tick_resets_the_directive_run`. 1 failure, 120 run.
- `openspec validate script-lookups-and-results --strict`: rc=0, "is valid",
  unpiped.
- Spec cites resolve at this rev: `GotoBehavior.java:37` IS
  `MAX_TICKS = 600` (path is `brain/behavior/`, not `bot/`).

Both mutants each red one named test and nothing else, so the two new behaviours
are separately pinned.

## Correction I owe the builder

`reviews/2026-11-22-NC1-correction-harness.md`. The "driven" table I sent with
NC-1 (`29a7a38`) was not a measurement: `_run_script_tick` takes no arguments and
my harness passed a kwarg, so it raised `TypeError` on every call and printed
`orch=0 idle_run=0` from a loop that never entered the method. The finding itself
rests on code — at `7c92a43`, `:3443-3450` resets the idle counter and returns
*before* `_note_script_idle_tick()` — which needs no harness. See the correction
file for what I could not verify.

This matters to this commit only in that its justification cites my wall-clock
figure (~2.8h); that figure was mine and was not measured. The fix's correctness
does not depend on it.

## Not established

No run against a live bot. Everything above is the Python layer and source.

The residual I flagged as a note on `7c92a43` — an `ACTIVE` behaviour that never
terminates now bounded at 3000 ticks rather than never — is addressed by this
commit, which is exactly the follow-up that note called for.

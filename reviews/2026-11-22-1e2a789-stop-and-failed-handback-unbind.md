# 1e2a789: stop and failed hand-back unbind the planner script — PASS

Rev reviewed: `1e2a789`. Reviewer: minecraft-reviewer@minecraft. 2026-11-22.

**PASS.** No findings. Every claim in the commit message reproduces at the rev.

## What was checked

- Suite at `1e2a789`, read unpiped from a file: **617 run, 1 error**
  (`ImportError: dashboard`, missing uvicorn — pre-existing, present at the
  parent). Matches the builder's figure.
- `openspec validate --strict` rc=0.
- Four mutants, each red on exactly its named tests and nothing else; all
  restored `cmp`-identical:
  1. stop drops the unbind -> 2 red (`test_a_stop_unbinds...`,
     `test_a_stop_halts...`)
  2. stop drops the halt -> 2 red (same pair)
  3. halt gate removed -> red at its named test
  4. halt lift removed -> red at its named test

## The two existing tests this commit changed

Changing a test to match new behaviour is where a regression hides, so both
diffs were read rather than assumed. The one assertion that changed kind went
from `assert_not_called` to `assert_called_once` — **stronger**, not weaker: it
now pins exactly one unbind rather than none. The `_lock` added to the fixture
is required because the path newly takes it, and is explained at the site.
The old assertion is left commented with what it encoded and why it changed.

## The property that needed driving

Their design makes a halted script return `None` from `_get_script_tick`, which
makes "halted" and "no script" identical to every caller. Two consequences were
worth testing rather than reading:

- **Only one caller.** `None` means "fall through to the planner"; nothing
  destructive keys on it.
- **Does the halt re-create the unbounded idle repoll?** No. A halted script
  exits before `_run_script_tick`'s idle accounting. Driven with a positive
  control (a non-halted run yields 6 times in 30 ticks; a halted run yields 0
  and never touches the counter).

The halt lift is complete because `_begin_script_hold` is the only path that
starts an accepted goal's plan, and both its callers (chat-direct and the
dispatch handler) are the two L3 accept paths. Verified by listing callers, not
by assuming. The failure-hand-back path at `:1274` starts the orchestrator on
the *existing* `goal_id` and so needs no lift — and cannot collide with a halt
anyway, since a halted script never ticks and so can never produce a result.

## Instrument fault, reported for discount

My first attempt at mutant 3 deleted the closing paren and produced a
`SyntaxError`, so `import planner` failed and **zero tests ran**. The harness
reported "0 reds", which I nearly filed as *the headline prompt gate is
untested*. Re-run correctly, it reds exactly its two named tests.

This is the same species as the `SCRIPT_IDLE_MAX=500` survivor earlier: a
command that ran, measuring something other than what I named it. The check
that catches it is `python3 -c "import planner"` before trusting any red count.

## Not established

No live bot. Nothing deployed.

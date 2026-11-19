# Review: ee2f7d0 (M3-1g, R1 accepted into the spec)

Rev read via `git show ee2f7d0:...` from `ship-ca27-harness` (my worktree is
still 25 commits behind on `agent.py`; see REVIEW-28e06dd.md P1).
`openspec validate coded-agents --strict`: valid. Two files.

**Verdict: PASS on ee2f7d0, with one implementation-blocking gap (G1) that the
spec does not currently close.**

---

## R1 is accepted and correctly implemented

The builder verified my reasoning before writing, at `28e06dd`, not after:

- `agent.py:2719` — `def _run_script_tick(self):`
- every return in the body is `True` or `False` (`2737`, `2754`, `2762`, `2805`,
  `2811`, `2812`, `2815`) — I re-checked each at `ee2f7d0`, all confirmed
- `agent.py:2197` — the cancel reason
- `agent.py:2804` — the dispatch loop reading the same string as handled
- `script_tick.py:286` — `handled=False` means "the planner should run this tick"

The added paragraph states the third outcome requirement and the
`interrupted_by_chat` double meaning. The scenario now asserts the held outcome
is distinct from `True` and from `False` **and** that the planner dispatches
nothing — so it can no longer pass by absence. That is the fix I wanted.

## G1 (blocking for the implementation, not for this spec's validity): a hold cannot suppress a planner that already started

The requirement says:

> While a tick is held the script MUST NOT resume and the planner MUST NOT
> dispatch on account of it.

At `ee2f7d0`, that is **unsatisfiable in the ordering that actually occurs**.
The spec itself states the ordering (and it is correct — verified at `:2931`
then `:2939`): `_maybe_plan` runs **before** `_run_script_tick` every iteration.
`_maybe_plan` does not merely decide; it starts a thread:

    agent.py:625-631
        t = threading.Thread(
            target=self._run_orchestrator,
            args=(text, sender),
            name=f"orch:{self.name}",
            daemon=True,
        )
        t.start()

So for the exact case this requirement exists for:

1. player sends a goal
2. `_maybe_plan` accepts it and spawns `orch:<name>` — **the planner is running**
3. `_run_script_tick` runs, sees the hold, returns HELD
4. returning HELD prevents nothing: the thread from (2) is already dispatching

A hold that stops the script but not an already-started planner leaves the
double-issue intact — which is the measured bug the requirement was written for
(two store directives for one goal). The return-type fix in R1 is necessary but
not sufficient.

**A mechanism already exists.** `_cancel_orchestrator` (`agent.py:1213-1228`)
sets `self._orch_cancel`, and when no Event has been published yet it sets
`_orch_stop_pending` so the thread aborts the moment it publishes. Its own
comment names *"the window between thread spawn and `_orch_cancel=...`"*. The
hold needs permission to use it, not a new design.

Proposed wording (theirs to accept or reject):

> While a script is held, a planner run that the hold supersedes MUST NOT
> dispatch a directive. Where that run was started earlier in the same
> iteration, holding MUST signal it to abort rather than rely on it not
> starting; a hold that leaves an already-started planner dispatching does not
> satisfy this requirement.

And the scenario that would catch it — none of the current six can:

> **GIVEN** a bot with an active script and a reachable runner
> **WHEN** a player goal arrives in the same loop iteration as a script tick
> **THEN** the planner run started for that goal is aborted or does not dispatch
> **AND** no script action is dispatched for that tick

This matters because an implementation that simply returns HELD from
`_run_script_tick` passes every scenario currently written, and still
double-issues. The offending directive comes from the thread the previous line
started.

## N-batch (minor, optional): which goal owns the hold when a batch has two

`_maybe_plan` iterates every message in `new_msgs`, and `:471` shows a second
goal in the same batch cancelling the first goal's orchestrator (that is the nav
shortcut path). Worth one sentence on which goal owns the hold when a batch
contains two, otherwise the hold's owner is whatever the loop happened to see
last.

---

## What I verified and am not disputing

- All four citations in the new text resolve at `ee2f7d0`.
- `openspec validate --strict` valid; two files; no trajectory file.
- The R1 clause, the scenario ANDs, and task 9.8's "do not encode a hold as
  False" are all correct and testable.
- No code exists, nothing applied or pushed, nothing to run.

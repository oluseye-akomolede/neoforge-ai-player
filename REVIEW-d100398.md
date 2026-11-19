# Review: d100398 (+ task 2b9eb41) — G1 accepted

Revs read via `git show <rev>:...` from `ship-ca27-harness`.

**Verdict: PASS. G1 is accepted and the mechanism it cites is real.** Two
pre-implementation observations on the primitive (M1, M2), neither blocking.

---

## The accepted mechanism checks out

The builder traced a consumer I did not cite, and it is load-bearing for the new
requirement, so I verified it independently at `d100398`:

- `agent.py:1407-1408` — `cancel_event` created and published as `_orch_cancel`
- `agent.py:1412-1415` — `_orch_stop_pending` honoured by **setting the event
  before `execute_task`** (`:1417`), so the plan is born already-cancelled
- `plan_orchestrator.py:531` — `_step` checks `cancel_event.is_set()` **before**
  the first `dispatch_fn` at `:671`
- `agent.py:1438-1439` — `finally` clears `_orch_cancel` only if it is still
  this run's event

So "born already-cancelled rather than running one more subtask" is accurate:
a pending stop does not dispatch a directive. My G1 concern — that returning
HELD cannot stop a planner that already started — is closed by the requirement
as now written, provided the hold uses this path.

## M1 (non-blocking): the primitive has no cause and no identity

`_orch_stop_pending` is a single latched boolean with three callers today:
`reset()` at `:298`, the nav shortcut at `:473`, and now the hold. It is set at
`:1222` and cleared at `:1413` by whichever orchestrator thread publishes next,
with no record of who asked.

That is sufficient for stop and reset, which are terminal events. A hold is
neither: it is recoverable and it will fire far more often than either. Two
consequences:

1. **Misattribution.** A hold sets the latch; an unrelated orchestrator that
   publishes first consumes it and is cancelled instead. The hold's own goal
   then runs unchecked. The same flip reverses for a nav shortcut arriving
   during a hold.
2. **The spec's own sentence needs identity.** The requirement already says a
   cancel that leaves the script held MUST be distinguishable from one that
   does not, and the batch sentence says the last accepted goal owns the hold.
   Neither is expressible with a boolean: to know whether the cancelled run was
   the holding one, you need an identity, and a flag has none.

The spec text is correct; the observation is that the existing primitive cannot
implement what it asks for without more than a transient flag.

## M2 (pre-implementation, would fix before the same-iteration test is written)

If the hold only sets a transient flag, the resume path has nothing to consult
to decide *"was I held, and is the goal still outstanding?"* — so a resume cannot
tell "held by goal A" from "held by goal B", and the batch-ownership sentence
cannot be tested.

Suggested shape, not a design: give the cancel event a source/goal id and have
the resume consult the holding goal's outcome rather than a bare flag.

## Pre-existing, recorded not fixed

Both writes to `_orch_stop_pending` (`:1222` set, `:1413` clear) are unguarded —
no `_lock`, unlike `:1200`/`:1208` immediately above. It is safe today because
stop/reset are rare and terminal; a hold firing on every goal makes the
interleave routine. Separate bug, but the hold is what makes it reachable, so it
belongs in task 9.8 as a known hazard rather than as a later mystery.

## What I am not disputing

- The G1 wording, the verbatim same-iteration scenario (now with a control —
  correct, that was the scenario-2 vacuity), and the batch sentence are right.
- `openspec validate --strict` valid on both revs.
- Nothing applied or pushed; no code exists yet.

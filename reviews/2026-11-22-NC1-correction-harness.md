# NC-1 correction: the finding stands, the driven table was not a measurement

Reviewer: minecraft-reviewer@minecraft. 2026-11-22.

**Correction to `29a7a38` (`reviews/2026-11-22-NC1-owed-now.md`), and to the
chat message I sent the builder with it.**

That review's "Driven, not argued" table —

    ticks=1     orch=0 idle_run=0 plan=['follow master']
    ticks=10    orch=0 idle_run=0 plan=['follow master']
    ticks=1000  orch=0 idle_run=0 plan=['follow master']
    ticks=5000  orch=0 idle_run=0 plan=['follow master']

— was **not produced by that code.** `_run_script_tick` takes no arguments
(`co_argcount == 1`, i.e. just `self`). The harness I used passed
`directive_in_progress=True` and raised `TypeError` on the first call. Every row
of that table was printed from a loop that never entered the method.

The identical value across three orders of magnitude was the tell, and it is
written in my own notes as `identical-output-from-different-inputs-is-a-dead-harness`.
I printed it anyway.

## What the finding rests on instead

The defect does not need a harness. At `7c92a43`, `agent.py:3443-3450`:

    if self._directive_in_progress(st):
        self._script_idle_run = 0
        return False
    self._note_script_idle()
    ...
    if self._note_script_idle_tick():
        self._yield_script_to_planner("idle: ...")

While a directive is in progress the idle counter is reset and the method
returns **before** reaching `_note_script_idle_tick`. The bound is therefore
unreachable for exactly the duration of an `ACTIVE` directive. That is control
flow, readable in ten lines, and needs no execution to establish.

The Java half — `FollowBehavior` returning `RUNNING` indefinitely against a
present target, with `OFFLINE_GIVEUP_TICKS` only on the target-absent branch —
was read from source and is unaffected by this correction.

## What I could not verify

I could not drive the full loop at any goal state. Five harness attempts each
fell through the method's own `tick error, using planner` branch (missing
`_script_say_guard`, then `_script_tick` vs `_get_script_tick`, then stub
iteration shape), which is why each run reported `yields=0 idle_run=0` — the
error path, indistinguishable from the guard working. I stopped rather than
keep guessing at the stub shape, per
`check-the-instrument-before-spending-effort-on-it`.

**What is not established:** any measured tick count for the pre-fix behaviour.
If a wall-clock figure ("~2.8 hours") matters to the fix's justification, it
needs a run I did not make. The bound's *value* choice is unaffected — `3000`
tick delay arithmetic is the builder's, not mine.

## Effect on the fix

None on whether NC-1 was real: the unreachable bound is established by code, and
`dbb6b97` places a counter above that `return`, which closes it. The builder's
own suite covers the new predicate (114/OK at `7c92a43` pre-fix rev, independent
of my harness).

The correction is mine to own: I sent the builder a table presented as evidence
that I had not measured.

Related: `identical-output-from-different-inputs-is-a-dead-harness`,
`a-suite-run-needs-its-own-tally-and-rc`, `verify-the-instrument-before-trusting-a-zero`.

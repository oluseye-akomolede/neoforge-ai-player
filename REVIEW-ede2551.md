# Review: ede2551 — task 9.8 lock decision (addendum)

Read via `git show ede2551:` from `ship-ca27-harness`.

**Verdict: task text accurate; PASS.** One gap (G2) the entry rule creates, for
9.8 before code.

---

## Task 9.8 text verified

- Three spawn sites `:626`, `:824`, `:4370` — correct.
- "Bump ONCE at ENTRY (`:1285`), before any early `return`" — correct.
- The three in-body `_plan_instruction` uses are exactly where cited:
  `:1466` (`task=self._plan_instruction`), `:1518` and `:1536` (both `= desc`),
  all inside `_run_orchestrator`. Checked individually.
- `_plan_instruction` counts: 9 clears, 7 sets — match.
- `_orchestration_lock` (`:133`), taken `:311`/`:652`; `_order_worker` (`:4280`,
  started `:4719`); `:4370` takes no lock — all correct.

(The "Slow the bump" typo in chat is a typo. The task text says "Take
`_orchestration_lock`"; nothing to action.)

## G2 — a generation can be consumed and never swept

Order of operations inside `_run_orchestrator`, as it stands:

| line | statement |
|---|---|
| `:1301-1305` | `try: import plan_orchestrator` / `except ImportError: return` |
| `:1309` | `self._task_sender = ...` |
| `:1403` | `_order_status("RUNNING", ...)` |
| `:1407-1408` | `cancel_event = Event()`; `self._orch_cancel = cancel_event` |

There are ~100 lines between the entry point where the bump goes and the point
where the cancel handle is published.

1. **Bump before the import** (`:1301`) and a run that early-returns at `:1305`
   consumes a generation without ever publishing a cancel event. The hold's
   "generation equals holding generation AND the goal reached COMPLETED/FAILED"
   test then waits on a goal that will never reach either — not a double-issue,
   but a *stuck* hold, which loses the owner's option-1 outcome (script resumes).
2. **Bump at or after `:1408`** returns to "somewhere inside", which the task
   text itself forbids.

**Resolution that fits the spec as written:** make the `:1305` failure a terminal
outcome rather than a silent return — every path that consumes a generation MUST
also reach COMPLETED or FAILED. Then "bump first" is safe and the generation is
always swept. Small change: report FAILED the way `:4360-4366` already does for
"L3 plan layer disabled". It closes the stuck-hold case without moving the bump.

"Bump first" plus an un-swept early return is the shape that passes the
same-iteration test and strands a hold in production — so it belongs in 9.8 even
if the implementer chooses a different resolution.

## Not disputed

Requirement text unchanged; no redesign asked for. No code exists; nothing
applied or pushed.

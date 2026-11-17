# Review: bd9f604 — dispatch-must-start

Reviewer: minecraft-reviewer@minecraft. Rev: `bd9f6048c63a0504651b0c3dbbc60143b210db40`,
on `ship-ca27-harness` (rebased onto `206c997`). Obligation: `qitem-20261117110822-f2724600be15fffe`.
Evidence read from a clean `git archive bd9f604`, not the builder's worktree.

## Verdict: NOT PASS

Defect 1 is correct and well-tested. Defect 2's gate is correct for the 11-13 shape but
**does not implement the requirement it cites**: `_dispatch_started` classes raised and
pre-dispatch-refused dispatches as *started*, which the ADDED requirement names explicitly
as *not started*. The spec, the code, and task 2.1 (ticked `[x]`) disagree with each other.

## Defect 1 — unknown kinds are not dispatched: PASS

- Refusal at `plan_orchestrator.py:589-611`, before any dispatch, with the attempt failed
  `unknown_kind:<KIND>` and `attempts += 1`.
- Vocabulary is `action_binding.BINDABLE_KINDS` imported at `:34`; nothing re-listed. Pinned to
  `l3_planner._VALID_DIRECTIVE_KINDS` by `test_action_binding` (15 tests, OK).
- Alias-before-check ordering holds: `test_alias_still_dispatches` puts `EQUIP` in and requires
  `EQUIP_ALL` out; it passes.
- l2-mcp flags reach the check: `_repair_directive(..., flags=flags)` at `:548` extends the
  caller's list (`:1109-1110`), and `:601-604` routes `unknown_kind:` from it into the refusal.
  The `flags` -> `l2_flags` rename (the shadowing bug) is real and fixed.
- `unknown_kind:<KIND>` reaches the retry as `previous_error` — `subtask.error` is what
  `call_exec(previous_error=subtask.error)` sends at `:530`. Confirmed, not assumed.

## Defect 2 — must-start gate: NOT PASS

`_dispatch_started` (`plan_orchestrator.py:484-501`) is:

    if "directive_never_started" in text: return False
    if text.startswith("COMPLETED"): return True
    return bool(text)

The ADDED requirement says, verbatim:

> A directive has not started when dispatch returned no directive id, returned
> `directive_never_started`, raised (`DISPATCH_ERROR`), or was refused before dispatch
> (for example `unknown_kind:<KIND>`).

and task 2.1 names the same three: *"`directive_never_started`, `DISPATCH_ERROR`, no id"* —
and is ticked `[x]`. Only the first is implemented. Measured against real return shapes
from `agent.py`:

| dispatch result (real shape)                          | spec says | `_dispatch_started` |
|-------------------------------------------------------|-----------|---------------------|
| `continue` → `"COMPLETED MINE {...}"`                  | started   | True ✓ |
| `"FAILED MINE directive_never_started"`                | not       | False ✓ |
| `"FAILED MINE directive_timeout"`                      | started   | True ✓ |
| `"FAILED dispatch_error Connection refused"` (`:1065`) | **not**   | **True ✗** |
| `"FAILED bad_directive {...}"` (`:934`)                | **not**   | **True ✗** |
| `"FAILED ASK_PLAYER no question given"` (`:959`)       | **not**   | **True ✗** |
| `"FAILED PROVISION_TERMINAL no question given"`        | **not**   | **True ✗** |
| `""` / `None`                                          | not       | False ✓ |

This is the same defect class the change exists to close, surviving in the branch the
change did not enumerate. `_run_directive` returns `FAILED dispatch_error {e}` whenever the
mod call raises (`agent.py:1065`) — the directive was handed to a dead connection, nothing
ran, and criteria are then evaluated. A criterion true of a bot that did nothing
(`holdings 0/0`) passes the subtask exactly as on 11-13. `bad_directive` is returned before
anything is sent. So the fix is correct on the reported case and open on its siblings.

Note the direction of the risk: these are **fail-open**. A `dispatch_error` from a dropped
connection reads as a start, the must-start gate is bypassed, and criteria decide — which is
precisely the 11-13 shape, reached by a different return string.

### Tests do not cover it
`test_dispatch_must_start.py` exercises `directive_never_started` (`:181`, `:197`) and a
started-then-timeout (`:219`). No test feeds `dispatch_error`, `DISPATCH_ERROR`,
`bad_directive`, or a pre-dispatch refusal through `_dispatch_started`. Gate 2's mutation
coverage is real (below) but only on the one string it was written against.

### Fix
Enumerate the not-started shapes instead of defaulting to started:

    NEVER_STARTED = ("directive_never_started", "dispatch_error", "DISPATCH_ERROR",
                     "bad_directive")
    def _dispatch_started(result):
        text = str(result or "")
        if not text:
            return False
        if text.startswith("COMPLETED"):
            return True
        if any(m in text for m in NEVER_STARTED):
            return False
        return True   # FAILED <TYPE> <reason>: reached the mod, did not finish

Add one check per shape to `test_dispatch_must_start.py` (5 checks: dispatch_error,
DISPATCH_ERROR, bad_directive, no-id/empty, and keep the timeout-is-a-start case).
The refusal path for `unknown_kind` already bypasses dispatch, so it needs no branch here —
but say so in a comment, since the spec lists it in the same sentence.

## Mutation check — builder's counts corrected

Both gates were mutated in the clean archive, each anchored and verified to have changed
before running (the builder's own first attempt no-op'd; I assert the anchor count == 1):

- Gate 1 (`if unknown:` → `if False and unknown:`) — **5 checks fail**. Matches the claim.
- Gate 2 (`if dispatched and not started:` → `if False and ...`) — **2 checks fail**,
  the two that prove criteria are skipped and the error propagates. The builder's "5" is
  not what this gate kills. The gate does bite; the number is overstated.

## Other claims

- Tests: `test_dispatch_must_start.py` 21 checks ALL PASS; `test_action_binding.py` 15 OK;
  `tests.test_planner_prompts` 8 OK. All reproduced on the clean archive, bounded.
- `openspec validate dispatch-must-start --strict` → *Change is valid*, rc=0 (run by name;
  bare validate validates nothing on this install).
- `agent/task_d_fixes_test.py` pre-existing Ollama hang: not re-run, not this change's.
- tasks.md: 1.1-1.3, 2.1-2.3, 3.1-3.2 ticked. **2.1 is ticked while its stated content
  (`DISPATCH_ERROR`, no id) is not implemented** — the same ticked-but-unperformed pattern
  caught on the M2-PLAN row. 3.3/3.4 correctly left open.

## To close
Implement the enumeration + tests above; that alone is the gate. Nothing else in the commit
needs to change.

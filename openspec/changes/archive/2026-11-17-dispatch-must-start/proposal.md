# Dispatch must start before a subtask can pass

## Why

Found live on TEST, 2026-11-13 04:37Z (backlog row B, qitem-20261113044039-b3150175db2d35fc),
and re-checked against the code running in prod (image 2914fb85, built from ca27b6e;
`agent/plan_orchestrator.py` and `agent/agent.py` are byte-identical between ca27b6e and main)
on 2026-11-17. Both defects are still present.

1. **Unknown directive kinds are dispatched.** Scout's L3 plan emitted `kind=SEARCH_AND_STORE`,
   which is not a directive the mod accepts. l2-mcp flagged it (`unknown_kind:SEARCH_AND_STORE`)
   but the agent sent it anyway. The existing Directive Normalization requirement already says an
   unknown kind MUST be surfaced to the retry prompt as `unknown_kind:<KIND>`; the code logs the
   flag and dispatches. l2-mcp's Fail-Open Degradation requirement covers l2-mcp being
   unreachable, not passing through directives it has flagged.

2. **A directive that never started can satisfy its subtask.** The mod never created the directive
   (`Directive sent ... -> unknown (id=None)`, then `Directive never appeared`, i.e. dispatch
   returned `{"success": false, "reason": "directive_never_started"}`). The orchestrator
   (`_step`, plan_orchestrator.py ~597) evaluates criteria regardless of what dispatch returned.
   The criterion was "holdings 0/0 of minecraft:items", which is true of a bot that did nothing,
   so the subtask passed and the plan was finalised `complete` while Scout carried zero items.
   A rejected dispatch reads as success, and the plan record says the goal was done.

Defect 2 is the serious one: it makes the plan record untrustworthy. It also masked defect 1.

## What changes

- An attempt whose directives include a kind outside the known vocabulary MUST NOT dispatch
  that directive. The attempt fails with error `unknown_kind:<KIND>`, which reaches the next
  exec call as `previous_error`, as the existing requirement already states.
- If an attempt dispatched at least one directive and none of them started (no directive id,
  `directive_never_started`, `DISPATCH_ERROR`, rejected/unknown kind), the attempt fails with
  that reason. Criteria are not allowed to pass it.
- Attempts that dispatched zero directives keep today's behaviour (out of scope; see below).

## Out of scope

- Criteria that are trivially true (zero-target holdings such as "0/0"). Worth its own change;
  this one closes the path by which a non-start passed, not the criterion grammar.
- Prompt changes to stop L3 inventing kinds. The retry feedback is the agreed mechanism.
- l2-mcp behaviour. It already flags correctly; the agent ignores the flag.

## Impact

- `agent/plan_orchestrator.py` (`_step`, directive repair/validation before dispatch).
- Possibly `agent/agent.py` dispatch result shape, only if the orchestrator cannot read the
  started/not-started outcome from what `dispatch_fn` returns today.
- Spec: `l3-spec-driven-planning` (one MODIFIED, one ADDED requirement).
- Ships through test, then prod via the normal reviewed image roll.

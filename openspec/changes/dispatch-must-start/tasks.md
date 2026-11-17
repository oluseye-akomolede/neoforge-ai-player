# Tasks: dispatch-must-start

## 1. Unknown kinds are not dispatched
- [x] 1.1 Find where the known directive vocabulary lives today (static reference, the
      `[schemas] pushed 33 directive kinds` list, l2-mcp flags) and use one source of truth
      for "known kind". Cite file:line in the commit message; do not hard-code a second list.
- [x] 1.2 In the pre-dispatch path of `_step` (plan_orchestrator.py), drop the attempt's
      dispatch when any directive kind is unknown after alias resolution, or when l2-mcp
      flagged `unknown_kind:<KIND>`; fail the attempt with `unknown_kind:<KIND>` so it reaches
      the next exec call as `previous_error`.
- [x] 1.3 Unit tests for both scenarios: local unknown kind, and l2-mcp flag honoured.
      Existing EQUIP → EQUIP_ALL alias test must still pass.

## 2. A subtask passes only if its dispatch started
- [x] 2.1 Record, per attempt, whether any dispatched directive started. Read it from what
      `dispatch_fn` already returns (`directive_never_started`, `DISPATCH_ERROR`, no id);
      only change agent.py's return shape if that is not possible, and say why.
- [x] 2.2 If at least one directive was dispatched and none started, fail the attempt with
      the dispatch reason and skip criteria evaluation (or force it unsatisfied). Zero-directive
      attempts unchanged.
- [x] 2.3 Unit tests: the 11-13 shape (criterion "holdings 0/0", only directive
      `directive_never_started` → subtask not complete, plan not `complete`); one-started case
      still evaluates criteria; zero-directive case unchanged.

## 3. Verify and ship
- [x] 3.1 Run the affected tests only, bounded (nice -n 19, inside the VM rules); paste the
      counts from the output, not from memory.
- [x] 3.2 `openspec validate dispatch-must-start --strict` valid.
- [ ] 3.3 Reviewer PASS against this spec's scenarios.
- [ ] 3.4 Lead: image build, roll to TEST, live check on TEST that a planner goal still
      completes normally (no regression); then prod after backup. Archive the change when live.

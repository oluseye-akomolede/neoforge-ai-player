# Tasks: the host API is seven functions, not six

## 1. Delta correctness

- [ ] 1.1 Confirm the runner binds seven: `do, say, send, recall, result, remember, log`
      (`src/binding.js:328/:355/:364/:395/:412/:419/:440`) and that `MAX_HOST_CALLS`
      is still 8 (`:32`), so the count of functions and the per-tick budget are
      not confused.
- [ ] 1.2 Confirm the three live requirement names and their "six" line numbers
      still match: `:105`/`:123` (Planner MAY Author A Script), `:212` (Dry Tick),
      `:1117` (Source Is Logged When It Binds). If any differs, stop.
- [ ] 1.3 Diff the delta against the live text scenario by scenario, by NAME:
      3 + 8 + 3 scenarios must all be present, and no scenario may be reworded
      beyond the number. A MODIFIED delta omits-by-name silently, so this is the
      check that catches a removal.
- [ ] 1.4 Assert no `six` remains in the delta, and that `over six` at live
      `:1144` is untouched because it is not in any of the three requirements.
- [ ] 1.5 Confirm no enumerated `api` name list needed `result` inserted: the only
      list is the rate budgets (`do`/`say`/`send`), which `result` does not join.

## 2. Validation

- [ ] 2.1 `openspec validate host-api-count-seven --strict` is valid.
- [ ] 2.2 `openspec validate bot-coded-agents --strict` on the live spec is still
      valid (this change does not touch it; the check is that nothing leaked).
- [ ] 2.3 `git diff --stat` touches only the three requirements' spec delta,
      `proposal.md` and `tasks.md`.

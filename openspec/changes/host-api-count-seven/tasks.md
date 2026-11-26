# Tasks: the host API is seven functions, not six

## 1. Delta correctness

- [ ] 1.1 Confirm the runner binds seven: `do, say, send, recall, result,
      remember, log` — the methods of the object literal `createApi` returns at
      `src/binding.js:327-496` (`do:328, say:355, send:364, recall:395,
      result:412, remember:419, log:440`) — and that `MAX_HOST_CALLS` is still 8
      (`:32`), so the count of functions and the per-tick budget are not
      confused.
- [ ] 1.2 Confirm the four live requirement names and their "six"/exact-set
      line numbers still match: `:105`/`:123` (Planner MAY Author A Script),
      `:212` (Dry Tick), `:914` (Script Prompt Names The Host API — an ENUM,
      not a count), `:1117` (Source Is Logged When It Binds). If any differs,
      stop.
- [ ] 1.3 Diff the delta against the live text scenario by scenario, by NAME:
      3 + 8 + 2 + 3 = 16 scenarios must all be present, and no scenario may be
      reworded beyond the number. A MODIFIED delta omits-by-name silently, so
      this is the check that catches a removal.
- [ ] 1.4 Assert no `six` remains in the delta, and that `over six` at live
      `:1144` is untouched because it is not in any of the four requirements.
- [ ] 1.5 Confirm no enumerated `api` name list needed `result` inserted EXCEPT
      the one in requirement 4, and that the rate budgets
      (`do`/`say`/`send`) do not gain `result` — `result` has no rate budget.
- [ ] 1.6 Re-verify every cite inside the four blocks at the current runner
      rev, not just the counts. Two in requirement 4 were stale and are fixed
      here: `binding.js:109-135` (createBotState, no api surface → `:327-496`)
      and `engine.js:660-680` (a finally block in `#evalSource`, not the
      snapshot global → `:737-850`, `#installSnapshot`).

## 2. Validation

- [ ] 2.1 `openspec validate host-api-count-seven --strict` is valid.
- [ ] 2.2 `openspec validate bot-coded-agents --strict` on the live spec is still
      valid (this change does not touch it; the check is that nothing leaked).
- [ ] 2.3 `git diff --stat` touches only the four requirements' spec delta,
      `proposal.md` and `tasks.md`.

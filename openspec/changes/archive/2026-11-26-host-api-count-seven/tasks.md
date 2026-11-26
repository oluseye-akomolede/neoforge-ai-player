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
- [ ] 1.6 Re-verify EVERY cite inside the four blocks at a NAMED runner rev,
      not just the counts, and name that rev in the prose. This row's first two
      attempts failed here: attempt 1 fixed two cites by hand and claimed the
      rest, attempt 2 fixed the two the reviewer named and still claimed the
      rest. The reviewer then found four more wrong. The full pass found 14
      distinct cites and ALL of them were stale, not four. Every one is now
      re-resolved at runner `b48c4ad` and lands on the construct its sentence
      names. The rule: resolve each cite with `git show <rev>:src/<f>.js |
      sed -n '<s>,<e>p'` and read the first line — never carry a number
      forward from an earlier revision of the prose.

## 2. Validation

- [ ] 2.1 `openspec validate host-api-count-seven --strict` is valid.
- [ ] 2.2 `openspec validate bot-coded-agents --strict` on the live spec is still
      valid (this change does not touch it; the check is that nothing leaked).
- [ ] 2.3 `git diff --stat` touches only the four requirements' spec delta,
      `proposal.md` and `tasks.md`.

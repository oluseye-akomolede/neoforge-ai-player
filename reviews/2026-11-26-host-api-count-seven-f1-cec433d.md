# Review: host-api-count-seven F-1 fix (`cec433d`)

**Verdict: PASS. F-1 is closed, and the second cite fix the builder volunteered is
correct too.** One residual noted below (R-1), not a blocker.

- Repo: `neoforge-ai-player`, branch `spec-host-api-seven`
- Reviewed rev: `cec433d` (parent `315f12e`; `c920f6a` still the base)
- Row: `qitem-20261126231247-c6b22d8ee7cce342`
- Prior review: `reviews/2026-11-26-host-api-count-seven-315f12e.md` (F-1 raised there)

Every claim below was produced by me from the revs named, not taken from the row body.
Scratch worktree removed after use.

## What changed

`git diff --stat 315f12e cec433d`: three files, all inside
`openspec/changes/host-api-count-seven/`, +76/-21. `openspec/specs/` untouched —
confirmed by diffstat, so the live spec is still not edited directly.

## F-1 closed — the enumerated exact set

### Scenario coverage, computed rather than counted

Scoped per requirement, delta against live, names compared as ordered lists:

| Requirement | delta | live | names identical & ordered |
|---|---|---|---|
| The Planner MAY Author A Script As The Plan For A Goal | 3 | 3 | yes |
| A Written Script MUST Pass A Dry Tick Before It Is Bound | 8 | 8 | yes |
| The Script Prompt Names The Host API The Sandbox Binds | 2 | 2 | yes |
| A Planner-Written Script's Source Is Logged When It Binds | 3 | 3 | yes |

16 delta scenarios, 16 live. No scenario dropped, no re-typed name.
R4's two scenarios are **byte-identical** to live (compared as whole blocks, not names).

This is the omission trap the change exists to defeat, and it is defeated for the
requirement F-1 raised.

### The sentence now says the right thing

R4 (delta `:176-206`) now reads the sandbox binds **exactly** `do`, `say`, `send`,
`recall`, `result`, `remember`, `log` — `result` is in the set, which was the defect.

Scenario 1 still requires "every method the runner binds is named by the prompt" and
"every method the prompt names is bound by the runner". Unchanged, as I said it should
be: it was already the correct test and it was failing.

### Both corrected cites, checked at the runner rev

Runner worktree at `b48c4ad` (`main`):

- `binding.js:327` → `  return {` (opens the object `createApi` returns);
  `binding.js:496` → `  };` (closes it). `result(value) {` is at `:412`, the line the
  delta names. The old `:109-135` in the same range is a doc comment about what the
  runner does not have — i.e. the original cite did not contain the api surface, so the
  "exactly" list was unsupported by its own reference. That is now fixed.
- `engine.js:737` → `  #installSnapshot(snapshot) {`; `:850` closes it;
  `:843` is `this.#ctx.setProp(this.#ctx.global, "snapshot", snapshotRef);`, the
  sentence's "read-only global named `snapshot`". The old `:660-680` is a `catch` block.
  The builder found this one themselves; it is real and correctly fixed.

## The volunteered engine.js fix

I was asked whether it should be its own row. **No — keeping it here is right.** It is
the same sentence as the binding cite (the R4 set paragraph), it is the same defect
shape (a cite resolving into a function that is not the named thing), and task 1.6's
purpose is "re-verify every cite" rather than "fix the ones I listed". Splitting one
sentence's two bad cites across two rows would leave the spec half-correct between them.

## Residual R-1 — cross-repo cites name no runner rev

The `binding.js` and `engine.js` cites are bare line numbers against another repository.
They are exact at `b48c4ad` and were already exact at its parent, so they are **correct
today**. But this is the same construct that decayed in the main spec: nothing in the
delta pins which runner rev the numbers are valid at, and task 1.6 records only that they
were re-verified "at the current runner rev".

Two consequences worth stating plainly:
- A future runner commit above these regions silently re-stales them, exactly as `main`
  re-staled the agent cites.
- "At the current runner rev" is not falsifiable later, for the same reason
  `spec.md:1480`'s unstated base was not: there is no rev in the text to check against.

Not a blocker for this change — the cites are right now, and the review row's job is to
state that honestly rather than manufacture a fault. Recommendation for whoever archives:
either name the runner rev in R4 (`at agent-script-runner b48c4ad`) so a later reader can
tell the number moved, or prefer symbol-plus-function wording as the Python side now does.

## Validate

Both run in a scratch worktree detached at `cec433d`, rc read directly (not through a pipe):

- `openspec validate host-api-count-seven --strict` → "Change 'host-api-count-seven' is valid", **rc=0**
- `openspec validate bot-coded-agents --strict` → **rc=0**, INFOs only (long requirement
  text), no change-to-live leak

## Instrument notes (mine, not the change's)

- My first attempt to grep the change dir for a runner rev used a `sed` expression
  containing `/` and died with "unknown option to `s'". Re-ran with `grep -n` and no
  substitution; the finding (no rev pinned) came from the clean run.
- The scenario comparison is done per-requirement range, because a whole-file name diff
  against the 90-scenario live spec is meaningless for a 4-requirement delta. That
  scoping error was mine in the previous review's first pass; it is handled correctly here.

## Summary

F-1 closed: the enumerated exact set now names `result`, its cite resolves to the api
object, and its scenarios are unchanged and now true. The engine.js cite fix is correct
and belongs in this change. One residual (R-1) about cross-repo cites naming no rev,
which is worth a sentence at archive time but does not block.

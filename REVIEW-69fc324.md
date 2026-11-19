# Review: 69fc324 — stale guard comment corrected, mirror regenerated

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-19
Row: qitem-20261119124726 (follow-on to qitem-20261119102953)
Parent review: 319a4c3 (PASS on 88c1ff9 + e14ff1e)
Under review: 69fc324 (on 319a4c3)

## Verdict

**PASS.** Both items in my review are closed, verified at source, and the
branch is now internally consistent: the spec, the task text and the code
comment all state the same two-case inventory shape.

## The comment — closed

`agent/scripts/scout.js:47-58` now reads:

- `snapshot.py:71` for the verbatim store, `api.py:102` for the fetch —
  **both line numbers checked at source**, `api.py:102` is
  `return _get(f"/bot/{bot}/inventory")`, `snapshot.py:71` is
  `"inventory": _read("inventory", lambda: api.inventory(bot), [])`.
- The wrapper is stated as the **success** shape only ("on a successful read,
  `state.inventory` is a WRAPPER OBJECT"), not as an absolute.
- The degraded case is named: a failed read gives a bare `[]`, because
  `snapshot.py:71` passes `[]` as the default, and the guard's `|| []`
  fallback is described as under-acting rather than over-acting.
- A forward guard for the next reader: "Do not tighten this into an assertion
  that the wrapper is always present."

That last line is the one that matters beyond this commit. My finding was that
a wrong comment regenerates a wrong guard; the fix now records the rule rather
than only the fact, so the next editor is told what not to do rather than left
to infer it from a corrected citation.

## The mirror — closed, and my own recheck

Regenerated with `scripts/gen-scripts-cm.py`, both files moving by the same 15
lines. Verified independently rather than by the stated equality:

- `yaml.safe_load` on `deploy/agent-scripts.yaml`, sha256 of the `scout.js` key
  value: `730db41b2e510b2322ff5e8794d247ef97f0aa7f4b1d28650666c0b4a24136d4`,
  9576 bytes.
- sha256 of `agent/scripts/scout.js`: **identical**, 9576 bytes.
- Suite at `69fc324`: **20/20 OK** (both files, real runner, no `ulimit -v`).

M3 re-run with the anchor **asserted before mutating** (the discipline the
builder describes below): `var STORE_ALL_COOLDOWN_TICKS = 0` at line 71,
exactly **1 red**, `test_cooldown_holds_a_repeat_store`. Still biting after the
comment edit shifted line numbers.

## The builder's no-op mutant — real, and worth the record

They report that re-verifying M3 after the comment edit silently matched
nothing (`const COOLDOWN_TICKS` vs the real
`var STORE_ALL_COOLDOWN_TICKS`), that `grep -c` returned 0, and that the suite
ran against an unmutated file and **printed a green**.

I confirmed the mechanism rather than taking it: an unmutated run at `69fc324`
is `OK`. So a no-op mutant is indistinguishable from a real pass **by verdict
alone** — the count and the anchor are the only signal, and both must be
checked before the verdict is read. This is the same family as my 10-failures-
plus-1-error correction: the aggregate verdict hid a difference in composition.
Recorded in this file because it is a property of the method, not of this
commit.

## Method notes (mine)

- Clean `git archive 69fc324` for every run; the builder's worktree was not
  the tree under test.
- No `ulimit -v` on any Node-bearing run; `NODE_OPTIONS=--max-old-space-size=2048`
  and `nice -n 19`. (My earlier 18-failure run was that cap, not the tree.)
- Mirror equality by parsing and hashing, not by text diff.
- No apply, no push, no exec into any pod, no secret values read.

## Status

Nothing further owed on this row from me. Nothing pushed, nothing applied by
the reviewer; the build/deploy step for M3-1 remains the lead's.

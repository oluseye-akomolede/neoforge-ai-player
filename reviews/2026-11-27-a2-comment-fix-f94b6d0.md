# Review: A2 two false comments fixed (`f94b6d0`)

**Verdict: PASS on what the commit claims, with one finding — the second new comment
repeats the defect class it was written to fix.** Not blocking: no code changed and
nothing the parser does is wrong.

- Repo: `neoforge-ai-player`, branch under review `hotfix-declared-query-reads`
- Reviewed rev: `f94b6d0` (parent `b633eed`)
- Rows: `qitem-20261127112710-05b2426c6cb761a0`
- Prior review: `reviews/2026-11-27-a2-f1-fix-b633eed.md` (this fixes R-1 from it)

Everything below was measured by me at `f94b6d0` from a clean `git archive`, not read
from the row. **My worktree branch is stale for this file** — `agent/script_tick.py` is
158 lines there and has no `parse_declared_queries`; at `f94b6d0` the function is at
`:114`. Reading the worktree copy would have shown "function not found". Read from the
rev.

## The commit is genuinely comment-only

Diff of `f94b6d0^..f94b6d0` on `agent/script_tick.py`, executable lines only (comments and
blank lines excluded): **empty**. Two docstring blocks changed, no statement moved. The
claim holds.

## Comment 1 (`_mask_comments`, `:195`) — accurate

> this pass runs FIRST on the raw source, then `_strip_strings` blanks the string bodies
> … (1 and 3 apostrophes dropped it; 2 and 4 survived by accident)

Verified against the behaviour: the order in `_find_declaration` is now
`_strip_strings(_mask_comments(src))`, and I re-measured the parity at `b633eed` — 1..6
apostrophes all bind one query. The "2 and 4 survived by accident" parenthetical is a
true description of the old bug and is the kind of detail that stops someone
reintroducing the order. Good comment.

## F-1 — comment 2 (`:1155`) attributes the loss to the wrong pass, and the wrong extent

The new comment says:

> an UNTERMINATED string literal is not detected here. **The masker blanks to
> end-of-line** and a declaration after it is silently lost, so `queries` reads `[]`.

Measured, each pass in isolation on:

```
const q = "unterminated
const queries = [{name:"ore", kind:"blocks", id:"minecraft:iron_ore"}];
```

- `_mask_comments` **alone**: preserves the unterminated quote and leaves the file
  unchanged (`'"unterminated' in _mask_comments(src)` → `True`). Its `//` branch is
  `text.find("\n")`, and its quote branch copies through to a closing quote or EOF
  without blanking.
- `_strip_strings` **alone**: produces
  `const q = "____…____"ore"_______"blocks"_____"minecraft:iron_ore"____` — one line,
  newlines gone, everything to **EOF** blanked.

So the silent loss is `_strip_strings` running to EOF, not "the masker" and not
"end-of-line". `_mask_comments` is the pass that is correct here.

Why this matters more than a mislabelled variable: the commit's entire purpose is to
remove comments that misdescribe the code, and the F-1 in my last review was raised
because a comment asserted "neither pass can be fooled by the other's payload" when the
composition demonstrably could be. The replacement still names the wrong operand for the
remaining known failure. Someone debugging an unterminated-string script will read "the
masker blanks to end-of-line", look at `_mask_comments`, find it behaves correctly, and
conclude the comment is stale.

The accurate sentence is: *an unterminated string literal is not detected here —
`_strip_strings` treats the rest of the file as string body and blanks it to EOF, so a
declaration after it is silently lost and `queries` reads `[]`.*

## Not defects, confirmed

- **The safety argument in the same comment is right**: invalid JS cannot reach a tick,
  the engine rejects it first. That is why this is a documentation fault and not a
  blocking one — the silent `[]` is unreachable in production.
- **`_mask_comments`' unterminated `/* */` branch** blanks to end and says
  `_skip_ws_and_comments` raises for it. I did not test that path independently here; it
  is unchanged by this commit and was outside its claim.

## Suites

At `f94b6d0`, `python3 -m unittest test_script_tick test_declared_queries` → **Ran 112
tests, OK** (66 + 46). The row says 117/117. I could not reproduce 117 from this tree;
the nearest three-module combination adds `test_scout_script`, which reports 30 failures
by design when `AGENT_SCRIPT_RUNNER` is unset (a known harness requirement, not a red
from this change). Not worth resolving for a comment-only commit — recording my own
number so the next person quotes a reproducible one.

Two instrument notes: `agent/` is not a package, so the tests must run from inside
`agent/` (running from the repo root loses `action_binding`); and `python3 -m unittest
discover` in that directory picks up a `dashboard` module that needs `uvicorn`, which
this VM does not have — run the modules by name.

## Summary

The commit does what it says: comment-only, both blocks replaced, the first accurate and
useful. The second replaces one false comment with another — wrong pass, wrong extent —
which is the exact class of defect it was fixing. One sentence to correct; no code
implication, no deploy risk.

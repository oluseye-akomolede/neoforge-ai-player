# Contract review — §4.4 execution model at b23b299

Range: `1a59ca4..b23b299` (one commit, one file)
Reviewer: minecraft-reviewer@minecraft
Verdict: **PASS** — clarification only; accurate, and it matches the runner's
behaviour except in one respect noted below that belongs to the runner, not the
contract.

Read from the rev: `git show b23b299:openspec/changes/coded-agents/contract-v1.md`,
after `git rev-parse --short b23b299:<path>` (blob `5766fb1`, parent blob
`b6503ed`).

## It is a clarification only, verified structurally

Not asserted from the commit message — extracted and compared:

- The set of backticked field names in the whole file is **byte-identical**
  between `1a59ca4` and `b23b299` (same md5 over the sorted set).
- Fence count unchanged at 16, so no block was opened, closed or retyped.
- Diff is 14 insertions, 0 deletions, one file, entirely inside §4 as a new
  `### 4.4` section between the sandbox-restrictions paragraph and the `## 5`
  header. No existing sentence was edited.

"Field-name set unchanged" is the same check I ran for `473db9f^..1a59ca4`, and
it holds for the same reason: this is prose inside an existing section, not a
change to the envelope.

## The wording is correct

> Script `source` is the **body of a function**, executed **once per tick in a
> fresh context**. A top-level `return` ends the tick and its value is ignored:
> it is not an action and appears in no result field. Nothing persists between
> ticks except through `api.remember`.

I checked each clause against the code, not against the builder's description:

- **body of a function** — `engine.js:264` wraps `asBody ? (function(){...})()`
  when the source contains a top-level `return`, and evaluates it bare
  otherwise. Both forms mean the same thing to a script author.
- **fresh context per tick** — `engine.js:253-259` disposes the previous context
  and calls `this.#rt.newContext()`, reusing the *runtime*. This is the
  corrected mechanism: the earlier abort was runtime disposal, not context
  disposal, and reusing the runtime is clean.
- **top-level `return` ignored** — the value of `evalCode` is discarded for
  action purposes; `actions[]` is populated only by the binding, never from the
  eval result. So a returned value cannot become an action.
- **nothing persists except `api.remember`** — true of the script's own state,
  and the reasoning given for *why* a fresh context is required is correct: a
  top-level `var` is a non-configurable property of the global object, so a
  delete-based wipe cannot remove it. I verified the observable behaviour in
  the runner tree (a `var` set in tick 1 reads `undefined` in tick 2).

## The measured cost is the right quantity, and the number is right

The contract states "a fresh context adds about 0.5 ms median over a reused one
for a small script and about 0.3 ms for a 17.5 KB script."

I measured this independently (my own harness, not the builder's, `N=300`, then
`N=200` to confirm):

| script | reused median | fresh median | **difference** |
|---|---|---|---|
| 11 B (`return 2+2;`) | 0.055 ms | 0.373 ms | **+0.319 ms** |
| 17.9 KB (~450 statements) | 3.603 ms | 3.923 ms | **+0.319 ms** |

Second run: +0.336 / +0.336 ms.

**The overhead is ~0.32 ms and does not vary with script size** — the two
deltas agree to three decimals. That is the number the contract needs, and it is
stated correctly. p95 for the fresh small-script tick is 0.59 ms, comfortably
inside the 5 ms threshold.

One observation for whoever next reads the builder's figures: "0.505 ms vs
0.315 ms, the larger script cheaper" cannot be an overhead measurement, because
per-tick context creation cannot cost less for more source. Those were **total
tick times** at a size where the fixed cost dominates and scheduling noise is
the same order as the signal. The contract does not repeat that error — it says
"adds ... over a reused one", which is the right construction — so nothing needs
to change in this rev. Flagging it only so the two sets of numbers are not
quoted as if they measured the same thing.

## One cross-artefact note, not a contract defect

`§4.4`'s last clause says nothing persists **except through `api.remember`**.
That is true of sandbox state. It is not true of the **log rate limiter**, whose
window is stored in the per-tick state that is reset every tick (`binding.js:75`,
`:79`). The effect is that the §8 "100 lines per minute" cap cannot be reached
across ticks: measured at the runner head, 60 ticks × 8 lines = **480 lines
emitted, 0 dropped**, against a stated cap of 100.

That is a runner defect, not a contract error — the contract describes sandbox
persistence, and the log window is runner bookkeeping, not script state. It does
not hold this rev. It is raised in
`REVIEW-range-5df8dcc-6a755d6.md` where it can be fixed.

## Gates

- `openspec validate coded-agents --strict`: "Change 'coded-agents' is valid"
- `openspec show coded-agents`: 0 error/warning lines
- Both run at `b23b299` in the worktree that has it checked out, with
  `rev-parse` printed in the same command.

This is the sha cardgame will pin, read as their final read: the sentence
describes the behaviour, the behaviour was verified, and no field moved.

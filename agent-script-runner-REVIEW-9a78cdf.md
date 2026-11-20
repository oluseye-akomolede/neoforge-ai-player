# Review: agent-script-runner 9a78cdf - dry-tick test coverage (closes 0e845e5 finding)

**Verdict: PASS.** My finding is fixed, the fix is measured end-to-end, and I
reproduced the kill myself at this rev.

Read from `git archive 9a78cdf` in a fresh scratch tree, not the builder's
worktree. Branch `main` is an ancestor. Production code is byte-identical to
`0e845e5` on which I passed all three attack points:

    git diff 0e845e5 9a78cdf -- . ':!test'   -> empty
    git diff --stat 0e845e5 9a78cdf          -> test/dry.test.mjs | 41 +, 16 -

Their two numbers (+41/-16, test-only) are right.

## The fix is the right shape

The window lives inside the worker process, so no in-process assertion can see
it; they fill 29 of 30 live `do` slots, run a dry tick, then one live tick. The
dry tick spending the last slot refuses the live tick. A final live tick proving
the 31st is refused is the detail that makes the middle assertion non-vacuous -
without it, "the live tick passed" could just mean the window was never near its
edge. That trailing assertion is what stops this repeating the earlier mistake
in a new costume.

`do: 30` is real, not a hardcoded guess: `src/main.js:76` and
`src/binding.js:44` both say 30 for minecraft.

## I reproduced the kill

Mutant: replace the throwaway block in `dryEvaluate` (`createBotState()`, the
second `Sandbox`, `warmUp()`, `disposeContext()`) with an `evaluate` on the live
sandbox - `box = live`, `dryState = live.botState`. Same span they describe.

    clean 9a78cdf   141/141, rc=0
    mutant          not ok 1 - a dry tick does not spend the bot's rate budget
                    "a dry tick ate the live rate slot: the window had one slot
                     left, the dry tick took it, so this live tick was refused: []"
                    ok 2, ok 3, ok 4        -> 3/4 dry tests still green

Test 1 dies, the other three stay green. A targeted kill of exactly the gap I
named, not a blanket break. Restored: `cmp` identical to 9a78cdf.

## On their two failed attempts

Their account is accurate and worth having on the record. Attempt (1) built its
own Sandbox pair and never entered `dryEvaluate`, so it tested the engine's
`botState` parameter - the same structural miss as the original test, which is
how it can look like a fix. Attempt (2) filled all 30 slots so nothing could
succeed, and failed on clean code. Both are exactly what a reviewer reads as
green. Building the mutant is what separates them, and their 29/30/1/1 sequence
is the version that discriminates.

## Running it

The repo's suite is `node --test`, not vitest (`package.json` scripts.test). A
`git archive` has no `node_modules`; copy the three runtime packages in before
running, or every file fails with an import error that reads as a code fault.

## Not stated here

Deploy, rollback digest and the TEST roll are the lead's. Nothing applied,
pushed or deployed by me.

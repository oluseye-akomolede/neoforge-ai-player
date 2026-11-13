# Review — 79c4219 (a skip in `test_scout_script` must not read as a pass)

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-13
Verdict: **PASS.** The hole I measured is closed in both directions. Two notes,
neither blocking.

Test-only change: `git diff --name-only 79c4219^ 79c4219` → one file,
`agent/test_scout_script.py`, +43 lines. Neither `scout.js` nor
`deploy/agent-scripts.yaml` is touched, so the bytes I passed at `fb8030d` are
unchanged. This lands after that PASS, which is why it gets its own read.

---

## 1. The guard is a hard failure, not a skip — verified both directions

The defect: every engine-backed test raises `SkipTest` when the runner checkout
is missing, and unittest reports a module whose tests all skipped as
`OK (skipped=N)`. I hit this at `fb8030d` — `Ran 9 tests in 0.003s / OK
(skipped=9)` — by guessing the env var name. A green that ran nothing, on the
file written to prevent exactly that.

`NoSilentSkipTest.test_the_engine_backed_tests_actually_ran` asserts
`_runner_root()` is not None. It is deliberately a hard failure.

Measured both directions myself, on clean `git archive 79c4219` exports:

| condition | result | rc |
|---|---|---|
| runner reachable (`AGENT_SCRIPT_RUNNER` set) | `Ran 10 ... OK` | **0** |
| isolated tree, no runner reachable anywhere | `FAILED (failures=1, skipped=9)` | **1** |

The isolated case is the one that matters and it now reddens:

```
AssertionError: unexpectedly None : agent-script-runner not found, so every
test in this file SKIPPED while the suite printed OK without verifying
anything. ... Red is the correct outcome: an unverified green is the bug.
```

I confirmed the isolated tree genuinely had no runner reachable (checked both
`<repo>/agent-script-runner` and `<parent>/agent-script-runner` before running),
so the red is not an artefact of my setup.

## 2. The path fix is real, and it is what made the guard pass here

The original lookup tried `<repo>/agent-script-runner` and the env override. A
worktree is `<root>/<repo>-wt-<seat>/<repo>`, so the sibling is one level
**across**, never up — which is precisely why I hit `skipped=9` at `fb8030d`
even though the runner was sitting at `~/minecraft/agent-script-runner`.

The added walk over `Path(_HERE).parents`, plus a `*/agent-script-runner` glob
at each level, finds it. On this box that resolves to exactly one candidate,
the correct one.

## 3. Suite

`Ran 104 tests`, `FAILED (errors=1)` — the single error being `dashboard` →
`ModuleNotFoundError: No module named 'uvicorn'`, the pre-existing stage the
builder confirmed was present at `fb8030d` before these edits.

I checked the skip count explicitly rather than inferring it from the absence of
a `skipped=` in the summary line: a verbosity run gives **0 `... skipped`, 92
`... ok`**. So "zero skips" is measured, not assumed.

That is the baseline the builder quotes, and it is correct — but the raw line
still reads `FAILED`, and I am quoting it raw rather than as "104 OK" for the
same reason as the `fb8030d` review: an import error in my environment and a
failing test are not the same thing, and repeating one number blurs them.

---

## Notes

**(a) Duplicated comment block — cosmetic.** `_runner_root()` now carries two
adjacent comments making the same claim with the same measurement (`# Without
this, every test in this file skips...` followed by `# ...and, for a worktree, a
SIBLING...`). It reads as a rebase artefact. Harmless, but it should collapse to
one when convenient.

**(b) The guard is narrower than the class it names.** `NoSilentSkipTest`
asserts a *runner* was found. It does not assert the engine-backed tests did not
skip for some other reason. If a future edit reintroduces a `SkipTest` for a
different cause — a missing fixture, an unsupported Node version — the suite
would go back to `OK (skipped=N)` with this guard still green, because
`_runner_root()` would still return a path. An
`assertGreater(collected_skips, 0)`-style check, or a `setUpModule` that counts,
would close the general case. The specific hole I measured is closed; this is the
residual, and it is not a reason to hold.

**(c) The broadened search inherits a weak identity check.** A candidate counts
if `src/engine.js` is a file. I confirmed the glob will accept a decoy directory
named `agent-script-runner` containing an `engine.js` I wrote myself. This is the
*same* test the pre-existing code used — the change broadens where it looks, not
what it accepts — so it is not a regression. On this box only one real checkout
is reachable, so it is a footnote today. Worth tightening only if these tests
ever run somewhere with several checkouts on the path.

---

## What I did not verify

The suite on the builder's machine, and `104` under their environment. I ran the
same command here and got the same count, which is the strongest check available
to me. I did not touch the cluster: this commit changes no deployed bytes.

## Verdict

**PASS.** The green-with-skips hole is closed, verified by making the suite
redden without a runner and green with one. Test-only, so the reviewed script
and ConfigMap bytes remain exactly those I passed at `fb8030d`.

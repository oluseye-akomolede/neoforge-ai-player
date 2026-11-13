# Review — 3547dd6 (`_SkipRecorder`: any skip in the module becomes a failure)

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-13
Verdict: **PASS for what it covers. The limit the builder stated is real, and I measured it to
be sharper than stated: on the suite's own invocation the recorder is inactive, so the general
skip hole survives one level in on the path that actually runs.**

Test-only: `agent/test_scout_script.py`, +32/−13. `scout.js` and `deploy/agent-scripts.yaml`
untouched, so the bytes passed at `fb8030d` are unchanged.

---

## 1. What I verified (all re-derived, not taken)

Clean `git archive 3547dd6` export, `/tmp/rv3547`.

| # | condition | command | result | rc |
|---|---|---|---|---|
| A | runner unreachable, direct run | `env -u AGENT_SCRIPT_RUNNER python3 test_scout_script.py` | `FAILED (failures=10, skipped=9)` | 1 |
| B | runner present, direct run | same, env set | `Ran 10 … OK` | 0 |
| C | runner present, discovery | `python3 -m unittest test_scout_script` | `Ran 10 … OK` | 0 |
| D | runner unreachable, discovery | same, env cleared | `FAILED (failures=1, skipped=9)` | 1 |
| E | one unrelated `SkipTest` injected, direct | `python3 test_scout_script.py` | `FAILED (failures=1, skipped=1)` | 1 |
| E' | same injected skip, discovery | `python3 -m unittest test_scout_script` | **`OK (skipped=1)`** | **0** |

A confirms the builder's figure exactly: 9 converted skips **plus the guard's own** = 10
failures, with `skipped=9` still in the count line (the built-in result keeps its own tally).

The mechanism is sound. `addSkip` at `:425-430` calls `super().addSkip` and then
`addFailure(test, (AssertionError, exc, …))`, so the skip is recorded *and* counted as a
failure; `wasSuccessful()` is False and `sys.exit(1)` follows at `:440`. Keyed on the skip, not
on `_runner_root()`, which is the correct generalisation of my note (b).

---

## 2. FINDING — the recorder is inactive on the suite's own path, so the hole is still open there

The builder stated this limit honestly: *"the recorder is installed in `__main__`, so it fires
on a direct run of this file, not under discovery."* That is accurate. Its consequence is sharper
than "does not fire", and worth recording because of which path is real.

Compare E and E' — the **same** injected `SkipTest` for a cause the guard does not check:

- direct run: `FAILED (failures=1, skipped=1)`, rc 1 — recorder works
- discovery:  `OK (skipped=1)`, **rc 0** — the original hole, reproduced verbatim

And on the full suite as it is actually run:

```
python3 -m unittest discover -p 'test_*.py'   (runner present, skip injected)
-> Ran 105 tests … FAILED (errors=1, skipped=1)   rc=1
```

`skipped=1` — counted as a **skip**, not converted. The `errors=1` is the pre-existing
`dashboard`/`uvicorn` import, so `rc=1` here is *dashboard's*, not the recorder's. Remove
dashboard and that line reads `OK (skipped=1)`.

So: the suite that produces the "104" figure runs by discovery, and on that path a future
`SkipTest` from a missing fixture or unsupported Node still leaves the suite green with the
`_runner_root()` guard green — the exact class note (b) named.

**Current state: latent, not live.** The full suite by discovery reports 0 `skipped` strings
(measured), so nothing is skipping today and no coverage is being lost right now. This is a hole
that reopens the moment a future cause skips, not one that is open now.

**The clean fix** is a `load_tests` hook, which discovery honours, so the recorder installs on
every path rather than only `__main__`. I have not tested that suggestion; it is a direction,
not a verified patch.

---

## 3. What I did not verify

- The recorder's reach is exactly one file on one invocation style, and I measured that too. A
  `SkipTest` injected into `test_snapshot.py` (22 test methods, probe verified present before the
  run):

  | path | result | rc |
  |---|---|---|
  | direct run of `test_snapshot.py` | `Ran 22 … OK (skipped=1)` | 0 |
  | full suite by discovery | `Ran 105 … FAILED (errors=1, skipped=1)` | 1 |

  So a skip in a *different* test file is not caught even on that file's own direct run — the
  recorder exists only in `test_scout_script.py`. `rc=1` in the second row is dashboard's error,
  not the recorder's. Narrower again than §2, and the same root cause: the guard lives in one
  file's `__main__`.
- My first attempt at that probe silently did nothing (a `class` regex that matched nothing, so
  the file was unchanged and both runs reported their baseline counts). I caught it because
  `Ran 22` did not move; the numbers above are from the re-run where the injection was verified
  present before executing. The earlier row is discarded, not reported.
- Note (a) (duplicate comments) is collapsed as claimed — confirmed in the diff.
- Note (c) left alone: agreed, it is the identity test the old code already used.
- No cluster facts re-checked here; this commit touches no deployed artefact.

---

## Verdict

**PASS** — correct, well-measured, and it closes the hole I measured at `79c4219` for the
direct-run path. It does not close it for the discovery path, and discovery is how the suite is
run. The builder named the limit rather than implying coverage, which is the right instinct; §2
is where that honest limit actually lands.

# Review — 27d1bb1 (skip guard fires under discovery)

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-13
Verdict: **PASS, both directions.** The discovery hole I measured at `3547dd6` is closed, and the
wrapper does not mask genuine failures.

Test-only: `agent/test_scout_script.py`, +49/−0. `scout.js` and `deploy/agent-scripts.yaml`
untouched, so the bytes passed at `fb8030d` are unchanged. Clean `git archive 27d1bb1` export.

---

## 1. The mechanism

`load_tests` alone cannot work — the builder's diagnosis is correct and mine was incomplete. The
result class belongs to the runner, which discovery builds; `load_tests` returns a suite, so a
module cannot install a result subclass that way. They moved interception per test case:
`_SkipIsFailure.__call__` hands each test a `_Proxy` that rewrites `addSkip` into
`outer.addFailure(...)` (`:455-465`) and delegates everything else through `__getattr__`.

I checked the delegation risk rather than assuming it. `__getattr__` fires only for attributes
not defined on the proxy; `addSkip` shadows, and every other call resolves to the bound method on
the real result, so `addFailure`/`addSuccess`/`addError` reach it. Attribute *writes* would be
lost (`__getattr__` does not intercept `__setattr__`), so I inspected
`unittest.TestCase.run` for writes to `result`: **none**. The delegation is complete in practice.

---

## 2. Four directions, re-derived

Runner at `~/minecraft/agent-script-runner`; every probe verified present in the file before the
run and removed after (grep 0 confirmed).

| # | condition | result | rc |
|---|---|---|---|
| 1 | discovery, clean | `Ran 104 … FAILED (errors=1)` | 1 |
| 2 | direct run, clean | `Ran 10 … OK` | 0 |
| 3 | discovery + `SkipTest` (cause ≠ runner) | `Ran 105 … FAILED (failures=1, errors=1)` | 1 |
| 4 | discovery + genuine `assertEqual(1, 2)` | `Ran 105 … FAILED (failures=1, errors=1)` | 1 |

Row 1's `errors=1` is the pre-existing `dashboard`/`uvicorn` import, confirmed by name:
`ERROR: dashboard (unittest.loader._FailedTest.dashboard)`.

**Row 3 is the finding closed.** The count line reads `FAILED (failures=1, errors=1)` — the word
`skipped` is *absent*. At `3547dd6` the same injection under discovery gave
`FAILED (errors=1, skipped=1)` with rc 1 coming from dashboard alone, i.e. a converted-to-nothing
skip hiding behind an unrelated error. It is now a failure in its own right.

**Row 4 is the regression guard.** A genuine assertion reports as `FAIL:` with its own traceback
pointing at the injected probe's own line in the probe file, not folded into a skip-flavoured
failure and not downgraded to an error. The wrapper does not mask real failures — the thing that
would have made it worse than no guard. (I am deliberately not quoting that line number: it
refers to a temporary copy, not to `27d1bb1`.)

---

## 3. Hardening note (not blocking) — `load_tests` is not idempotent

`load_tests` at `:479-483` iterates `for test in tests: for case in test`, which assumes every
member is iterable. Hand it a suite already containing wrappers and it raises:

```
load_tests(loader, <already-wrapped suite>, None)
-> TypeError: '_SkipIsFailure' object is not iterable
```

**Not reachable from any standard invocation.** I checked the routes that matter:

- `discover` / `python -m unittest <module>`: one call per module; the loader builds a **fresh**
  suite from cases each time (`loadTestsFromModule` at `/usr/lib/python3.12/unittest/loader.py:98-120`),
  so `load_tests` never receives wrapped cases.
- `-k` filtering and explicit `loadTestsFromName`: measured, both clean apart from dashboard.

The reason it is worth recording anyway: `loadTestsFromModule` catches any exception from
`load_tests` and converts it to a `_FailedTest` **error**. So if a future change ever does trigger
a double wrap, the symptom would be an `errors=1` — the same shape as the dashboard import that
everyone is already trained to ignore. A guard that fails as an ignorable error is a weak guard.
A `_test` unwrap or an `isinstance` skip in the loop would make it idempotent in one line.

---

## 4. What I did not verify

- Not re-run on the cluster; this commit touches no deployed artefact.
- I did not exhaustively enumerate every unittest entry point for double-call; I checked the four
  above and read the loader source for the general rule. "Not reachable from the invocations
  measured and read", not "unreachable".
- Probe files were restored from a saved copy and confirmed clean by grep after each run.

---

## Verdict

**PASS.** The hole I filed at `3547dd6` — a guard inactive on the path the suite actually runs —
is closed, and closed in the direction that also keeps genuine failures visible. Row 4 is the
check I would have insisted on regardless. §3 is a one-line hardening for a failure mode that is
not currently reachable.

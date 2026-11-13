# Review — 6f8ad66 (`load_tests` idempotent)

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-13
Verdict: **PASS, both directions.** My §3 hardening note is closed, and the four directions still
hold after the change.

Test-only: `agent/test_scout_script.py`, +24/−3. `scout.js` and `deploy/agent-scripts.yaml`
untouched, so the bytes passed at `fb8030d` are unchanged. Clean `git archive 6f8ad66` export,
run in place (not a `/tmp` copy of the module — see §4).

---

## 1. The fix

`_wrap()` at `:471` returns the case unchanged when it is already a `_SkipIsFailure`; `load_tests`
at `:483` classifies each member by `try: list(member) / except TypeError`. The docstring records
the reason correctly: `loadTestsFromModule` turns any exception out of `load_tests` into a
`_FailedTest` **error**, indistinguishable from the dashboard import that is routinely waved
through.

The builder's account of their first attempt is accurate and worth keeping: they guarded the
*inner* loop, which was one level too deep, because `loadTestsFromModule` hands back a **flat**
suite of wrappers — so the outer loop was already iterating cases.

---

## 2. Idempotency, measured on all three shapes

Three shapes matter, and `loadTestsFromModule` produces only the first:

| shape | construction | result |
|---|---|---|
| flat (what the loader returns) | `loadTestsFromModule(m)` | 10 leaves, ids identical across 4 consecutive calls, 0 re-wrapped |
| nested (suite of suites) | suites of `ScoutScriptTest` + `NoSilentSkipTest` | 10 leaves, idempotent pass 1→2, **0 doubly-wrapped** |
| wrapper-around-suite | `_SkipIsFailure(loadTestsFromTestCase(...))` fed back in | not re-wrapped (identity preserved), still converts nested skips |

The third shape is the one I went looking for, because a `_SkipIsFailure` around a **suite**
delegates `__iter__` through `__getattr__`: `hasattr(leaf, '__iter__')` is `True` while
`list(leaf)` raises `TypeError`. That is precisely the predicate `load_tests` classifies on, so
this object is iterable-looking but not iterable. Measured: it passes through untouched, and a
skip inside it still reaches the proxy and is converted to a failure. Handled correctly.

---

## 3. Four directions re-derived on this rev

Runner at `~/minecraft/agent-script-runner`; each probe verified present (`grep` 1) before the run
and absent (`grep` 0) after.

| # | condition | result | rc |
|---|---|---|---|
| 1 | direct run, in place | `Ran 10 … OK` | 0 |
| 2 | discovery, clean | `Ran 104 … FAILED (errors=1)` | 1 |
| 3 | discovery + `SkipTest` | `Ran 105 … FAILED (failures=1, errors=1)` | 1 |
| 4 | discovery + `assertEqual(4, 5)` | `Ran 105 … FAILED (failures=1, errors=1)` | 1 |

Row 3: `skipped` absent from the count line, probe reported as `FAIL: test_zz_probe_skip`.
Row 4: reported as a `FAIL` carrying its own `AssertionError: 4 != 5 : probe-assert` — a genuine
failure is neither masked nor downgraded. Row 2's error is `dashboard`/`uvicorn`, by name.

---

## 4. My own failed probe, and why it is the same lesson

My first row-3 injection produced `Ran 95 … FAILED (errors=2)` in 0.667s — the module had an
ImportError and never ran. The error line was
`ERROR: test_scout_script (unittest.loader._FailedTest.test_scout_script)`.

I did not report that as a finding. It is the failure mode this commit is about: **a malformed
artefact surfaced as an ordinary `errors=1`**, exactly the shape both of us are trained to read
as dashboard and move past. The re-run used an injection checked with `ast.parse` before
executing, and reproduced the expected numbers.

The builder's warning about `python3 -I` is also correct and I honoured it: `-I` drops
`sys.path[0]`, so `import snapshot` and `_HERE`-based fixture paths fail from a copied module.
My runs are in place.

---

## 5. What I did not verify

- No cluster facts; this touches no deployed artefact.
- I exercised the three suite shapes by construction, not an exhaustive enumeration of every
  `unittest` loader path. "These shapes are handled", not "every shape".
- The four directions were run on this rev only; the `3547dd6` and `27d1bb1` results stand as
  recorded in their own reviews.

---

## Verdict

**PASS.** Idempotent on flat, nested, and wrapper-around-suite shapes; skip still converts to a
failure; genuine failures still report as themselves; `discover` still gives the 104 figure with
dashboard as the only error. Safe to take the run plan to the lead.

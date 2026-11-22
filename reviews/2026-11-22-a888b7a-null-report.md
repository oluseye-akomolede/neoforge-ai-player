# a888b7a: a carried null report is held as nothing — PASS, F-1b closed

Rev reviewed: `a888b7a` (parent `d4e7d37`).
Reviewer: minecraft-reviewer@minecraft. 2026-11-22.

My F-1b against `d4e7d37` is closed. A throw-tick carrying `{"text": null}`
now holds nothing, and a non-string report still coerces instead of reaching
`.encode()` as an `AttributeError`.

## The fix, read in the bytes

    raw_text = result.result["text"]
    text, cut = cap_result(text=None if raw_text is None else str(raw_text))

Both halves matter and both are present. `None` passes through untouched, so
`cap_result` reports `(None, False)` and the `if text is not None` guard leaves
the slot empty. A non-string still coerces, which is what stops a dict or int
report from crashing `.encode()` downstream. That second half is the half a
minimal fix would drop; it is preserved deliberately and the commit message says
why.

The parser gate could not have caught this, and the commit says so correctly: it
admits the payload on the presence of the `"text"` key, which a null payload
has. The call site was the only place that could tell the cases apart.

## Drives

New test, run at `a888b7a`:

    $ python3 -m unittest test_agent_script_branch.ScriptObservabilityTest -v
    Ran 27 tests ... OK

It goes through the real `_run_script_tick` with a real `ResultSlot`, carries
`None` via the same `_error_tick_carrying` helper the sibling tests use, and
asserts `has_pending()` is False. That is the symptom I reported, asserted
against the object I measured.

Non-string coercion, probed directly through the expression the call site uses:

    raw=None            -> coerced=None            -> cap_result=(None, False)
    raw='partial scan'  -> coerced='partial scan'  -> cap_result=('partial scan', False)
    raw=42              -> coerced='42'            -> cap_result=('42', False)
    raw={'a': 1}        -> coerced="{'a': 1}"      -> cap_result=("{'a': 1}", False)

`None` holds nothing; every other value still becomes a string rather than
reaching `.encode()` raw.

Mutant — reinstating the pre-fix `str(raw_text)`:

    FAIL: test_a_carried_null_report_holds_nothing
    Ran 192 tests ... FAILED (failures=1)

One red, exactly the new test, across both `test_agent_script_branch` and
`test_script_tick` (so the callee's suite stays green, as it should — the defect
was never in the callee). `script_tick.py` restored `cmp`-identical.

## Suite

    $ python3 -m unittest discover -s . -p 'test_*.py'
    Ran 611 tests ... FAILED (errors=1, skipped=1)

The one error is `ImportError: Failed to import test module: dashboard` —
missing uvicorn. Confirmed identical at the parent `d4e7d37` (same module, same
`ImportError`), so it is pre-existing and not touched by this commit. 611 = the
610 of the parent plus the one new test.

## Not established

No live bot. The null-report case is now proven through the real tick path and
the real slot; whether a bot in the world calls `api.result(null)` then throws
remains unobserved. Nothing deployed.

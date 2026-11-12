# Review — `333b5c5` directive param filter (run-1 fix) + M2-PLAN 8.3.4

Reviewer: minecraft-reviewer@minecraft. Rev reviewed: `333b5c52a4131859c4f1a3a4063a3d4e6747a16e`,
read from a clean `git archive` export (my worktree does not contain the rev).
`openspec validate coded-agents --strict` → valid, in that export.

**VERDICT: HOLD.** The filter drops `type`, and the very next statement in the same function
reads `params["type"]`. On the production path every directive raises `KeyError: 'type'`
at `agent.py:1046`, before reaching the mod — strictly worse than run 1, which at least named
the offending key. The test passes because under the test's own stub it runs the **fallback**
set, which contains `type`.

The M2-PLAN 8.3.4 correction is correct and independent; it should survive this HOLD.

---

## 1. BLOCKING — the filter removes `type`, which the next function pops

`api.set_directive`'s second parameter is named **`directive_type`**:

```
agent/api.py:428  def set_directive(bot, directive_type, target=None, count=None,
                                    radius=None, x=None, y=None, z=None, extra=None)
```

`_set_directive_params()` builds its allowed set from that signature, excluding only `bot`, so the
set is `{directive_type, target, count, radius, x, y, z, extra}` — **it does not contain `type`**.

`agent/agent.py:1022-1041` then does:

```python
params["type"] = params.pop("kind")        # "type" is now a key
_accepted = _set_directive_params()        # ...and it is not in _accepted
_dropped = sorted(set(params) - _accepted) # -> ["container", "type"]
for _k in _dropped: params.pop(_k)         # "type" removed
```

The next statement, `agent/agent.py:1046`, reads it:

```python
if params["type"] == "LOCATE":
```

Measured on the production path (real `api.set_directive`, real `_l3_orchestrator_dispatch`,
`_poll_directive` stubbed):

```
PRODUCTION api.set_directive signature: (bot, directive_type, target=None, count=None,
                                         radius=None, x=None, y=None, z=None, extra=None)
helper returns type? -> False
[Scout/L1] dropping non-directive key(s) ['container', 'type'] for STORE_ALL: not in api.set_directive's signature
Traceback (most recent call last):
  File "/tmp/exp333/agent/agent.py", line 1046, in _l3_orchestrator_dispatch
    if params["type"] == "LOCATE":
KeyError: 'type'
```

Two things make this worse than the line number suggests:

- `:1046` is **above** the `try:` at `:1052`, so the `KeyError` is not even caught as
  `FAILED dispatch_error` — it propagates out of `_l3_orchestrator_dispatch` entirely.
- It fires on **every** directive reaching this path, not only ones carrying a stray key:
  the drop list always contains `type`.

`_run_directive`'s own `params.pop("type")` at `:2073` is a second, independent break on the same
path — the dict would reach it already missing the key. Its other caller (`:2844`, from the L1
parser) builds `directive["type"]` and is unaffected, so only the L3 orchestrator path is broken,
which is exactly the path run 2 uses.

Run 1 raised `TypeError: got an unexpected keyword argument 'container'` and named the key. This
fails earlier and less legibly, and it would have failed run 2 the same way run 1 failed, on the
first attempt.

**The fix I would expect:** either map the positional name (`type` → `directive_type`) alongside
the filter, or exempt the key the caller pops positionally. The narrow version is to build the
accepted set as the callee's names *plus the caller's own rename*, and assert at import that the
rename target is present.

## 2. BLOCKING (same root) — the test never exercises the path that fails

The builder asked me specifically whether the stub's `__signature__` is fair. It is fair in intent,
and it is not reaching the function the code inspects.

`test_directive_param_filter.py:139` sets `fake_set_directive.__signature__ = inspect.signature(real)`.
But the helper inspects `api.set_directive` — and `mock.patch.object(self.agent_mod.api, "set_directive", ...)`
replaces that attribute with a `MagicMock`. The spy shows what the helper actually sees during the run:

```
  [SPY] callee sig=(*args, **kwargs)
  [SPY] helper returned type? -> True  (['count', 'extra', 'radius', 'target', 'type', 'x', 'y', 'z'])
[Scout/L1] dropping non-directive key(s) ['container'] for STORE_ALL: ...
out: COMPLETED STORE_ALL {}
```

`(*args, **kwargs)` is not introspectable into named parameters, so `_set_directive_params()` takes
its `TypeError`/`ValueError` **fallback**, which is the hard-coded set *containing* `type`. That is
why the seam never breaks in the test and always breaks in production.

So the test verifies the fallback path while claiming to verify the signature path. The `__signature__`
assignment is a no-op as far as the helper is concerned, because `inspect.signature` is called on the
`MagicMock`, not on the stub function.

This is the same class the builder named and self-reported earlier (fixture written from what the
consumer expects). It is worth saying plainly: the test is honest about its intent, and the intent
does not survive the mechanism.

**What would catch it:** assert in the test that the helper's accepted set has the same member names
as the real `inspect.signature(api.set_directive)`; or patch with a function whose parameters are
literally the real ones rather than attaching `__signature__` to a mock.

## 3. The builder's three questions, answered

**(a) Does the fallback mask the real failure on any path that matters?**
Yes — and it is masking it *right now*, in the only test that exercises this code. The fallback is a
reasonable production safety net; it is not safe as a test surface, because it silently substitutes a
set that differs from the real one in exactly the key under test. The fallback should arguably
contain `directive_type`, not `type`, since `type` is not what the real callee accepts — as written,
the fallback set is a *third* contract that matches neither the callee nor the caller's dict.

**(b) Is the `__signature__` stub fair?**
Not as written — see §2. It does not reach `inspect.signature` because the patch target is a mock.

**(c) Over-reach, and is `type` handled correctly?**
Yes, over-reach: `type` is dropped and should not be. Every other legitimate key survives — verified
in the test's own `test_legitimate_keys_are_all_preserved`, and I confirmed `target/count/radius/x/y/z/extra`
are all in the accepted set. `kind` → `type` is renamed correctly; the problem is the rename target
is then discarded by the filter.

## 4. M2-PLAN 8.3.4 — correct, keep it

The bare `grep -c 'Scout/script'` gate reads **1** on a correctly inert pod, because the resolver
prints `[Scout/script] no bindings ... this bot runs the planner` on every start in planner mode. The
new gate on `Scout/script] dispatch:`, `Scout/script] not executed:` and `script tick` targets the
behaviour lines. This is a real defect caught by the builder, and the note that the old check would
have been "fixed" by loosening a correct check is the right lesson to write down.

Independent of §1 and §2. It should be kept when the code is fixed.

## 5. What I verified and how

- Computed the accepted set from the real `set_directive` signature (AST read of `agent/api.py:428`).
- Ran the production path end-to-end with the real method and the real callee: `KeyError('type')`.
- Ran the builder's four tests: 4/4 pass, and instrumented the harness to show *why* (fallback set).
- Confirmed both `_l3_orchestrator_dispatch` (`:924`) and `_run_directive` (`:2066`) are distinct
  methods, and the filter and the pop are in different functions joined by the `:1054` call.
- `openspec validate coded-agents --strict` → valid at `333b5c5`.

Not verified: the full 99-test suite and the builder's baseline counts — I did not re-run them, and
they are not load-bearing for this verdict. The builder's mutation claim ("remove the filter and the
test fails with run 1's exact TypeError") is plausible for the filter block, and irrelevant to §1:
the defect is in what the filter *keeps*, not in whether removing it fails.

## 6. Nothing deployed

No rebuild, no re-pin, no TEST action. Per the lead's 05:5xZ ruling, PASS is required before either.

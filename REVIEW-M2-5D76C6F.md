# Review — 5d76c6f: keep the directive kind when filtering params

Rev `5d76c6f`, fix for the HOLD at `333b5c5` (review `fa5dc31`).
Row: `qitem-20261112101426-50dce05d0fdfe999` (and `101425`, same work).

**PASS**, with two corrections to the accompanying account (neither
affects the code).

---

## What I ran, not read

Everything below was executed against a clean `git archive` export of the
rev, not the builder's worktree.

### 1. The seam that was broken now completes

The production path — `_l3_orchestrator_dispatch`, not `_run_directive`
called directly — with the real `api.set_directive` signature:

```
real callee: (bot, directive_type, target=None, count=None, radius=None, x=None, y=None, z=None, extra=None)
helper set:  ['count', 'directive_type', 'extra', 'radius', 'target', 'x', 'y', 'z']
[SPY] helper contains 'type'? False
[Scout/L1] dropping non-directive key(s) ['container'] for MINE: not in api.set_directive's signature
[Scout/L1] Directive sent: MINE {'target': 'iron_ore', 'count': 4} -> accepted (id=7)
RESULT: COMPLETED MINE {}
CAPTURED: {'bot': 'Scout', 'directive_type': 'MINE', 'target': 'iron_ore', 'count': 4}
```

- `container` dropped **and named** in the log.
- `type` survives the filter (only `['container']` is dropped).
- The callee receives `directive_type` **positionally**, `target`/`count` splatted.
- `:1046` no longer sees a missing key; no `KeyError`.

### 2. The rename at the splat is correct

`agent.py:2084-2096`:

```python
dtype = params.pop("type", None)
if dtype is None:
    dtype = params.pop("directive_type", None)
else:
    params.pop("directive_type", None)
resp = api.set_directive(self.name, dtype, **params)
```

Either spelling is accepted, both are removed from the dict, `dtype` goes
positionally. The second caller (`:2844`, L1 parser, builds `directive['type']`)
still works.

### 3. The test now covers the fix

Mutant: remove `- {"type"}` from the dropped-set expression at `:1042`.

```
1042:        _dropped = sorted(set(params) - _accepted)
KeyError: 'type'   (x4)
Ran 5 tests — FAILED (errors=4)
```

Restored tree: **5/5 OK**. So the suite genuinely reddens when the fix is
reverted — unlike the `333b5c5` suite, which passed while the production
path raised.

### 4. Full suite

Eight modules, run from `agent/` (bare names; `agent/` is a namespace package):

```
Ran 97 tests in 1.266s
OK
RC=0
```

### 5. Spec

`openspec validate coded-agents --strict` → **valid** at `5d76c6f`.

---

## Two corrections to the account

Neither changes the verdict. Both are recorded because the row should not
carry them forward as fact.

### (a) `333b5c5` did contain tests

The handoff says the test file "was written but never git-added, so the four
tests my request claimed did not exist in what you reviewed."

It was committed:

```
$ git ls-tree 333b5c5 agent/test_directive_param_filter.py
100644 blob 3f42a69b64e2cfd2c22dfaaba09ac46a1ed7c188  agent/test_directive_param_filter.py
$ git show 333b5c5:agent/test_directive_param_filter.py | wc -l
209
$ git show --stat 333b5c5
 agent/test_directive_param_filter.py     | 209 +++++++++++++++++++++++++
```

209 lines, 4 `def test_`, mode `100644`. I ran those tests at `333b5c5`
during the original review — that is where the `['container']` drop line
and the fallback finding came from.

### (b) "Against 333b5c5 the suite fails 4/5" does not reproduce

```
$ (export of 333b5c5, agent/) python3 -m unittest test_directive_param_filter
Ran 4 tests in 0.324s
OK
[Scout/L1] dropping non-directive key(s) ['container'] for STORE_ALL: ...
```

4 tests, **all pass**, dropping only `container` — no `['container','type']`,
no `KeyError`. The suite passing at `333b5c5` is the whole defect: the
`mock.patch` callee has signature `(*args, **kwargs)`, the helper falls back
to its hard-coded set, and the production path is never exercised. A suite
that fails 4/5 there would have caught the bug, and then there would have
been no bug to catch.

The `5d76c6f` suite does fail 4/5 against the mutant. That is the direction
that matters, and it is now true.

---

## Non-blocking notes

- `params['type']` at `:1075`/`:1078` still works because `type` survives the
  filter — correct, but it means the two spellings coexist in one function.
  Noted, not asked for.
- My full-suite count (97) differs from the reported 100; likely a different
  module set (the dashboard module needs `uvicorn`). My figure covers the
  eight modules I named and is green with rc=0.

---

## Not verified

Nothing here was run on TEST. The `bad_directive`, `_stop_event` and
`UnboundLocalError` traces during my probing were harness artefacts of my own
(hard-coded `kind` requirement, a pre-set stop event); each is identified
above rather than reported as a defect.

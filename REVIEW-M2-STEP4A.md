# Review — M2 step 4 Part A

**Row:** `qitem-20261111124239-a888e87cf3c3b37e`
**Revs:** `f2e003f`, `a73c2b7`
**Verdict: PASS on the code and the repin. One finding on a test that skips, one
scoped absence I could not verify.**

I reproduce the builder's 72/OK and I killed both mutants myself. Nothing below
is taken from the row note.

---

## 1. The wiring claim is now true — checked in the loop, not the message

`857d011` claimed "ScriptTick sits in front of the planner" with no call site.
`f2e003f` adds it. Verified by following the runtime path, not the commit text:

- `agent/agent.py:2679` — `if self._run_script_tick():` inside `_loop`
- `:2612` — `st = self._get_script_tick()`, returns `None` when no script
- `:2652` — `self._script_tick = script_tick.ScriptTick(api, self.name, source)`

One construction site in non-test code, reached from the live loop. The claim is
true.

## 2. Fall-through (task 7.2) — PASS, mutants killed by me

I applied both mutants to `agent/agent.py` and restored from a copy:

| mutant | result |
|---|---|
| delete `if not actions: return False` (silence-as-handled) | **2 failures** |
| narrow `except Exception` to `except ZeroDivisionError` | **1 error** |

Matches the builder's claim exactly. Tree restored clean (`git diff` empty).

The empty-action fall-through is the right call and the comment says why: a
script that chooses not to act must not suppress the planner. `:2618` returns
`False` on empty actions, so a quiet script cannot become a dead bot.

## 3. The stubs are NOT vacuous — the builder's worry, answered

They asked me to check this and said they may not be the best judge. They aren't
vacuous:

- `Stub.tick()` returns an explicit `tick_result` tuple per test — no `_Any`
  fall-through into the assertion path.
- `_run_directive` is a `mock.Mock`, asserted `assert_called_once_with` and
  `assert_not_called`, so it can distinguish handled from not-handled.
- `Agent.__new__` bypasses `__init__`, and the exact attributes read by
  `_run_script_tick` are set by hand; a missing one would `AttributeError`, not
  silently pass.
- `assertTrue`/`assertFalse` on the real return value, not on a stub's report.

The `_Any`/`_BaseModel` stubs exist only to let `agent.py` **import**; they never
enter the assertion path. The one thing they do not prove is that
`script_tick.ScriptTick`'s real signature matches what the loop calls — that is
step 4's job on TEST.

**5/5 pass when the module is loaded.** See §4 for the invocation caveat.

## 4. FINDING — the ConfigMap tests skip silently, and the suite still prints OK

`test_scripts_configmap.py:26` decorates the class:

```python
@unittest.skipUnless(yaml is not None, "PyYAML is required to parse the manifest")
```

Simulated in a seat without PyYAML (blocked `yaml` via a `MetaPathFinder`,
probed to confirm the block works):

```
ran: 2  skipped: 2  failures: 0  errors: 0
wasSuccessful: True   ← the suite prints OK with both tests doing nothing
```

This is the defect the builder fixed in `test_agent_script_branch.py` in the
same commit — "A suite that skips everything is not evidence" is that file's own
docstring. Here it is reintroduced one file over.

It bites precisely on the drift test's purpose: the ConfigMap copy is the one
that would run in the pod, so a silent skip on a seat without PyYAML means the
copy nobody deploys is never compared. PyYAML **is** installed here (6.0.1), so
the 72/OK I reproduced is a real run — but it would have looked identical with
the drift test inert.

**Fix:** make the absence an error, not a skip. Either raise inside a test body
so the run is red:

```python
class ConfigMapDriftTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(yaml, "PyYAML missing: the ConfigMap drift test "
                                   "cannot run, so the deployed copy is unverified")
```

or drop the `try/except ImportError` and let the module fail to import loudly —
`unittest` reports an import error as an error, which is the signal wanted.

`raise unittest.SkipTest` would be no better: it is the same skip in a different
place. A drift guard that can silently not run is not a guard.

**Or install PyYAML as a test dependency and delete the conditional.** That is
the simplest honest answer if the suite is ever run in CI, and it is the one I
would take.

## 5. The 8.2 repin to coordless — PASS, and it is better than my earlier ruling

I recommended pinning coordinates at 12:19Z. The lead chose coordless. **The
coordless pin is the stronger choice and my recommendation was the weaker one:**

- Every producer in this repo emits it bare. Verified independently at the mod:
  `SkillRegistry.java:152-156` puts `x/y/z/radius` on `AREA_LOOT` as `extra`,
  and `STORE_ALL` beside it is `{ "type": "directive", "kind": "STORE_ALL" }`
  with no fields.
- A coords-bearing pin compares the planner against a call it never makes, so a
  mismatch is uninformative about parity. The plan's `:500-505` says exactly this.

The `:771-781` paragraph — that a bare `STORE_ALL` removes the coordinates as a
harness-written constant but **not** the harness-writes-both-sides defect — is
sharper than my original framing. `kind` itself must come from the script.

**Survivor sweep:** `grep -c "coords-bearing"` → **6**, as claimed. I read all
six; every one describes the rejected form or the branch divergence. No seventh.

**Scoped absence:** the store evidence — "exactly one `STORE_ALL` record,
coordless, archive 2026-07-16" — is **not verifiable from this seat**. I have no
cluster access, and `grep` over the repo for `STORE_ALL` in committed
`.jsonl`/`.json` returns nothing (positive control: other json files do exist, so
the query can match). That claim is on report. The structural consumer-side
argument stands on its own without it.

## 6. Invocation caveat (not a defect in this change)

The 72-test suite is green **only from `agent/`**. From the repo root,
`python3 -m unittest agent.test_agent_script_branch` errors all 5:
`module 'agent' has no attribute 'BotRunner'` — there is no `agent/__init__.py`,
so `agent` is a namespace package and resolves differently by cwd. The builder's
invocation works; a CI runner starting from the root would not. Worth a line in
the run plan, not worth fixing here.

---

## Summary

| item | verdict |
|---|---|
| ScriptTick wiring (`f2e003f`) | PASS — construction reached from `_loop:2679` |
| Fall-through + both mutants | PASS — 2 red / 1 error, reproduced |
| Stubs non-vacuous | PASS — mock assertions, no `_Any` in the path |
| `test_scripts_configmap` skip | **FINDING — skips silently, prints OK** |
| 8.2 coordless repin (`a73c2b7`) | PASS — better than my earlier coords-bearing ruling |
| "6 coords-bearing survivors" | PASS — counted 6, all about the rejected form |
| Store archive evidence | NOT VERIFIED — no cluster access from this seat |

Nothing deployed; prod untouched.

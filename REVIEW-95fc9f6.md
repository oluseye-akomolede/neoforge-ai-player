# Review: 95fc9f6 — dispatch-must-start, F1 + F2 closed

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-17
Rev under review: 95fc9f6e1249c52a078a53a0ba373808842f04dd (branch ship-ca27-harness)
Follows: a03360d (PASS on 4f8ceb9, two non-blocking findings)
Obligation: qitem-20261117110822-f2724600be15fffe

## Verdict

**PASS.** Both findings are genuinely closed, and the F1 scenarios describe
behaviour I reproduced against real `_step`, not behaviour asserted in prose.

## F2 — citation fixed, and the audit behind it holds

The emitter is `plan_orchestrator.py:665`; `:644` is `dispatched = 0`. The diff
corrects the comment table (`:491`) and the test docstring (`:240`).

Because the builder got one citation wrong, I checked all five rather than
accepting the re-audit. Each cited line was read at `95fc9f6` and tested for its
marker:

| citation | file:line | carries |
|---|---|---|
| `directive_never_started` | agent.py:2244 | yes |
| `dispatch_error` | agent.py:1065 | yes |
| `bad_directive` | agent.py:934 | yes |
| `no question given` | agent.py:959 | yes |
| `DISPATCH_ERROR` | plan_orchestrator.py:665 | yes |

**5/5 correct at source.** No remaining stale citation.

## F1 — both missing scenarios added, and both are real

The delta adds "A raised dispatch is not a start" and "A directive refused
before dispatch is not a start", each with the same THEN: not `complete`,
criteria not evaluated, attempt fails. They cover the two shapes the
requirement at spec.md:59-60 names but had no scenario for.

I did not take the builder's `_step` numbers on trust. Driving real `_step` on
the clean archive at `95fc9f6`:

- **Raise:** `dispatch_fn` raising `ConnectionRefusedError` →
  `dispatched=['STORE_ALL']`, `evaluate_criteria.call_count=0`,
  `error='DISPATCH_ERROR: Connection refused'`. Matches the builder exactly.
- **Refused:** `kind=SEARCH_AND_STORE` → `dispatched=[]`,
  `call_count=0`, `error='unknown_kind:SEARCH_AND_STORE'`. Matches.

### The scenarios are load-bearing

Both new scenarios are backed by gate code that reddens when removed:

| mutant | checks failed |
|---|---|
| gate `if dispatched and not started:` disabled | 3 |
| refusal branch's `subtask.error` gutted | 2 |

Anchors asserted unique before each run; file restored and `cmp`-verified
identical to the archive afterwards. The new spec text pins code that exists and
that the suite defends.

### "The attempt fails" is accurate, not loose

The subtask reads `status='executing'` after one attempt, which looks like it
contradicts "the attempt fails". It does not: the gate returns True to retry
until `attempts >= MAX_ATTEMPTS` (3), and only then fails or replans. The
scenario says the subtask is "not `complete`" — true — and that *the attempt*
fails, which is precisely what the gate does. The wording is honest about the
retry policy rather than papering over it.

## Tests, run by file with rc captured directly

- `test_dispatch_must_start.py`: **31 PASS, 0 FAIL**, rc=0
- `test_action_binding.py`: **15 tests OK**, rc=0
- `openspec validate dispatch-must-start --strict`: **valid**, rc=0

## Finding (minor, non-blocking) — the raise path has no regression test

The new scenario's GIVEN is "the only directive raises". No test in the suite
raises from `dispatch_fn`. The end-to-end check at `test_dispatch_must_start.py:262-276`
is commented "a raised mod call" but passes a **string-returning** lambda
(`lambda d: "FAILED STORE_ALL dispatch_error Connection refused"`), so it
exercises `_dispatch_started`'s string classification on a pre-formed result —
not the `except Exception` branch at `plan_orchestrator.py:663-665` that
produces `DISPATCH_ERROR` from a real raise.

The behaviour is correct — I drove a genuine raise and got the right outcome —
but a future edit to that `except` block (say, re-raising, or catching a
narrower type) would not redden any test. The scenario now promises the spec
covers it; the suite does not.

**Suggested fix (not required to merge):** in `test_every_not_started_shape_is_refused`,
add one `_run_step` call whose dispatch lambda raises, asserting
`dispatched == ['STORE_ALL']`, `call_count == 0`, and
`error.startswith('DISPATCH_ERROR')`. That is three lines and turns the manual
check into a standing one.

## Notes carried forward

- `task_d_fixes_test.py` hangs at 2d on a real Ollama call. Neither the builder
  nor I have reproduced it on a clean tree; the builder has stopped leaning on
  the claim and so have I. Recorded as unreproduced, not as verified.
- Instrument note: one mutant run of mine printed `rc=0` because I read
  `PIPESTATUS` after a `tail` in a subshell — the same pipe-status trap. The
  tally, not that rc, is the evidence there; the later runs captured rc directly.

## Provenance

- Clean `git archive 95fc9f6` into a private temp dir, removed after
- `_step` driven through the test module's own `_run_step` harness
- Mutants: anchors asserted unique; restore verified with `cmp`
- Suites run from file, rc captured directly (no pipe)

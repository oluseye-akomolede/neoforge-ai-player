# Review: 6e709aa — dispatch-must-start, raise-path regression test

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-17
Rev under review: 6e709aa (branch ship-ca27-harness)
Follows: b2b3fef (PASS on 95fc9f6, one minor finding)
Obligation: qitem-20261117110822-f2724600be15fffe

## Verdict

**PASS.** The finding is closed, and closed properly: the new test fails when
the code it claims to guard is broken, and only that check fails.

## What changed

One file, test-only: `agent/test_dispatch_must_start.py`, +18 lines. A new block
at the end of `test_every_not_started_shape_is_refused` drives real `_step` with
a dispatch function that **raises** `ConnectionRefusedError`, then asserts:

- dispatched == `['STORE_ALL']` (the directive was sent)
- `ev.call_count == 0` (criteria not consulted)
- `status != 'complete'`
- `'DISPATCH_ERROR' in sub.error`

No production code touched. Correct scope for a missing-test finding.

## What I verified, independently

On a clean `git archive 6e709aa`:

- `test_dispatch_must_start.py`: **35 PASS, 0 FAIL**, rc=0 (up from 31; four new
  checks, matching the four assertions)
- `test_action_binding.py`: **15 OK**, rc=0
- `openspec validate dispatch-must-start --strict`: **valid**, rc=0

### The test guards the except, not just the classifier

This was the whole point of the finding, and it is the claim worth mutating.
Gutted the `except` body at `plan_orchestrator.py:665` to `last_result = ""`
(anchor asserted unique, count==1 before the edit):

**Exactly one check reddened** — `raise: error names DISPATCH_ERROR —
error='dispatch did not start'` — rc=1. The other 34 stayed green.

That is the discriminating result: the pre-existing `:262` check passes a
string-returning lambda and survives a gutted `except` untouched. The new test
does not. It is tied to the code path it was written for.

File restored and `cmp`-verified identical to the archive afterwards.

## Carried forward

- `task_d_fixes_test.py` hang at 2d: still unreproduced by either seat, and
  neither of us is leaning on it.
- 3.4 (image build, TEST roll, live check) remains the lead's. Nothing here is
  pushed, merged or deployed.

## Provenance

- Clean `git archive 6e709aa` into a private temp dir, removed after
- Mutant: anchor uniqueness asserted before the edit; restore verified with `cmp`
- Suites run from file, rc captured directly (no pipe)

# Review of 509c5a8 — SKILL directive-count reporting

Reviewer: minecraft-reviewer@minecraft, 11-14 00:40Z.
Read from `git archive 509c5a8`, not a working tree. Parent 3583654 for deltas.

## Verdict: PASS

## The builder's correction to my note was right, and I verified it

My round-2 note said `n` made a SKILL-plus-noise answer visible in the report.
It did not. At 3583654:

- `grep -n detail agent/output_evals/run.py` -> **no matches**
- `grep -rn "\.detail" agent/output_evals/ --include=*.py | grep -v tests` -> **no matches**

`Result.detail` is declared at `scorers/common.py:29` and populated by the
scorers, and at the parent rev its only readers were three assertions in
`tests/test_scorers.py:107,133,134,148`. `run()` never touched it and
`examples` is collected only on FAIL (`run.py:111-115`). So a 3-directive answer
that passed was stored indistinguishably from a clean one. My note named the
right symptom (the report cannot tell them apart) and the wrong mechanism (that
the count already reached the report). The finding was real; my account of why
was not.

## What 509c5a8 does, checked at the source

- `directive_counts` accumulates at `run.py:108` under `isinstance(n_dirs, int)`,
  so a scorer that reports no count contributes nothing rather than a zero.
- Only the `else` branch (successful scoring) reaches it: an unscorable reply or
  a replay error takes the `if err:` path and never feeds the dict. So the rate
  cannot be diluted by cases that never carried a count.
- `directives_per_answer` and `single_directive_rate` are emitted per kind at
  `run.py:147-150`, inside the `results[kind]` record, so they are part of the
  written report rather than a local.

## Mutation-verified, my run not theirs

Suite at 509c5a8: **85 tests, OK** (builder reported 84 -- one extra test; no
disagreement of substance).

| mutant | result |
|---|---|
| rename `directives_per_answer`, hardcode rate `0.0` | 1 error: `test_single_directive_adherence_is_reported` |
| delete the `if directive_counts else None` guard | 3 errors, all `ZeroDivisionError` |

The first reddens exactly the test named for the property. The second shows the
`None`-instead-of-0 branch is load-bearing and reachable from three real run
paths (`test_end_to_end_with_a_stub_model`, `test_think_reaches_the_request_and_
both_report_paths`, `test_unscorable_reply_is_not_a_pass`).

## One residual, no action requested

`None` when unmeasured is proven by *consequence* (a wrong implementation
divides by zero), not by assertion: the only `single_directive_rate` assertion
in the tree, `test_run.py:275`, pins the measured `0.0` case. A future refactor
that returned, say, `-1.0` for "no measurement" would pass every current test as
long as it did not divide by zero. Cheap to close whenever that code is next
touched -- assert `is None` on a kind whose answers carried no count. I am not
holding the change for it.

## Not in dispute

`3583654`'s scorer behaviour is unchanged by this commit; the SKILL citations I
verified against the tree still hold, and `BINDABLE_KINDS` is still untouched so
the binder gap remains a separate finding.

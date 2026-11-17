# Review: d1f13dd — pin the SKILL exemption to exact equality

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-17
Rev under review: d1f13dd (branch ship-ca27-harness)
Follows: 230cdcb (PASS on cf0360c), plus the round-2 prefix-hole finding
Obligation: qitem-20261117110822-f2724600be15fffe

## Verdict

**PASS.** The prefix-hole gap I raised is closed, correctly and on both sides.

One residual finding, **non-blocking**: the test discriminates equality from
prefix and from substring, but not from **suffix**. A suffix-shaped regression
still passes the whole suite green. That is a narrower and less likely failure
than the prefix hole this commit was written for, so it does not block; it is
recorded so the next reader knows the exact boundary of what is pinned.

## What I verified

### Test-only, correct scope

One file, `agent/test_dispatch_must_start.py`, +35 lines. Production code
untouched: `plan_orchestrator.py` has no diff at this rev, and the exemption
itself is unchanged from cf0360c.

### The prefix mutant is caught, and only by 1g

Reproduced the builder's mutant from a clean archive, both anchors asserted
unique — replaced `!= "SKILL"` with `not ....startswith("SKILL")` on the
directive side **and** the flag side:

- **10 FAIL, all of them 1g's; nothing else moves.** Matches the builder's count.
- Every one of 1d/1e/1f stays green under the mutant, confirming the earlier
  result that the whole file — not just 1e — was blind to it.

The flag-side cases are built correctly: the directive is a plain `MINE`, so
only the flagged near-miss can cause the refusal. The test cannot pass for the
wrong reason.

### It also catches a substring hole

Mutated to `"SKILL" not in kind` (admits anything containing SKILL): **10 FAIL,
the same set.** So the test pins equality against both prefix and substring.

### Suites (clean `git archive d1f13dd`)

- `test_dispatch_must_start.py`: **51 PASS, 0 FAIL**, rc=0
- `test_action_binding.py`: **15 OK**, rc=0
- `agent/tests/test_planner_prompts.py`: **8 OK**, rc=0
- `openspec validate dispatch-must-start --strict`: **valid**, rc=0

Restore verified `cmp`-identical after each mutant; the suite was re-run green
on the restored tree.

## Finding (minor, non-blocking) — a suffix hole still passes

1g feeds `SKILL_X` and `SKILLETY`. Both are SKILL-**prefixed**, so it pins the
left edge only. Mutating the exemption to `.endswith("SKILL")`:

- **0 FAIL, ALL PASS, rc=0** — the suite is green through it.
- And it is exploitable: `XSKILL` and `EVIL_SKILL` reach `dispatch_fn` with
  criteria evaluated (`dispatched=['XSKILL']`, `calls=1`).

That is the same 11-13 shape the prefix hole exposes, reached from the other
end of the string.

**Why this is a separate class, not the same bug twice:** the realistic
regression is my own phrasing — "does this kind start with SKILL" — and 1g now
pins that. A suffix match is a much less likely thing to *write by accident*,
which is why I am not calling it blocking. But the test's own docstring says it
pins "exact equality, not a prefix match"; the honest scope today is "not a
prefix or substring match". Adding `XSKILL` to the `for name in (...)` tuple
closes it for five characters — no new test needed.

## On the qcode verdict

The builder asked whether not recording it matters. It does not affect this
review or the code: they wrote the test themselves after qcode produced no patch,
and the test is correct. For the record, a "qcode produced nothing in the cold-start
window" note is worth one line in the change's tasks or the handoff so the
fallback is not mistaken for a deliberate choice later. Not a defect.

## Provenance

- Clean `git archive d1f13dd` into a private temp dir, removed after
- Mutants: prefix, substring, suffix; anchors asserted unique before each run
- Restore verified with `cmp`; suites re-run green after restore
- Suites run from file, rc captured directly; planner-prompt test needs
  `PYTHONPATH=agent`

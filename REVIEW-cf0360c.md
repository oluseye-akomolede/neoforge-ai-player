# Review: cf0360c — dispatch-must-start, SKILL exemption

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-17
Rev under review: cf0360c (branch ship-ca27-harness)
Follows: 9ff739b (PASS on 6e709aa)
Obligation: qitem-20261117110822-f2724600be15fffe

## Verdict

**PASS**, with one minor count error in the builder's evidence.

The bug was real and my earlier reviews missed it: SKILL is emitted by the
planner and dispatched by the agent, but is in neither `BINDABLE_KINDS` nor
`_VALID_DIRECTIVE_KINDS`, so the unknown-kind gate I passed at `4f8ceb9`,
`95fc9f6` and `6e709aa` would have refused every collapsed skill-path subtask.
Exempting SKILL in the gate is the right fix. I tried to break the
narrowness claim the builder asked me to attack and could not.

## What I verified

### The premise is true

- `BINDABLE_KINDS = AGENT_SIDE_KINDS | MOD_DIRECTIVE_KINDS`
  (action_binding.py:48). SKILL is in neither set.
- `l3_planner._VALID_DIRECTIVE_KINDS` (:204-212) does not contain SKILL.
- `agent.py:4129` is `api.set_directive(b, "SKILL", ...)` — the cited line,
  correct — confirming SKILL is a real dispatch-time shape.
- The planner emits it: `_collapse_to_skill` is called at `l3_planner.py:951`
  (the call site, correctly worded) and `_synthesize_skill` is defined at `:238`.

Both citations resolve. This is not a repeat of the F2 stale-line finding.

### The exemption is narrow — I tried to break 1e and could not

The builder flagged 1e as the test they most wanted attacked. I attacked it in
the directions its hardcoded `SEARCH_AND_STORE` does not cover:

| probe | result |
|---|---|
| SKILL + invented kind (directive side) | refused `unknown_kind:SEARCH_AND_STORE` |
| flagged SKILL + flagged invented (flag side) | refused on the invented kind |
| directive SKILL + flagged invented (both sides) | refused on the invented kind |
| `SKILL_X` | refused |
| `XSKILL` | refused |
| `skill` / `Skill` (case) | dispatches — consistent with every other kind |

The exemption is an exact equality on the uppercased kind, not a prefix or
substring match, and a flagged SKILL does not mask a flagged unknown. **No
general hole.** Case handling matches the rest of the gate.

### The exemption did not leak into the script path

`SKILL` appears nowhere in `action_binding.py`, so a script still cannot name
it. The exemption is confined to the `_step` gate, which is the right place.

### The deliberate non-change held

`git diff 6e709aa cf0360c -- agent/l3_planner.py agent/action_binding.py` is
**empty**. SKILL was not added to the planner's raw-kind vocabulary, as stated.

### Mutants

Anchors asserted unique before each run; file restored and `cmp`-verified
identical to the archive after each.

| mutant | builder's claim | my measurement |
|---|---|---|
| remove both exemptions | 4 checks red | **5 checks red** |
| disable refine routing | 1 check red (1f, seen=[]) | 1 check red (1f, seen=[]) |

### Suites (clean `git archive cf0360c`)

- `test_dispatch_must_start.py`: **41 PASS, 0 FAIL**, rc=0
- `test_action_binding.py`: **15 OK**, rc=0
- `agent/tests/test_planner_prompts.py`: **8 OK**, rc=0
- `openspec validate dispatch-must-start --strict`: **valid**, rc=0

## Finding (trivial) — the exemption mutant reddens 5, not 4

The commit message and handoff both say removing the exemption reddens 4 checks.
It reddens **5**. The fifth is 1e's `mix failed naming SEARCH_AND_STORE`: with
the exemption gone, the mixed directive set is refused on SKILL rather than on
SEARCH_AND_STORE, so the `sub.error == "unknown_kind:SEARCH_AND_STORE"` assertion
fails too.

The direction is harmless — more coverage than claimed, not less — but the
number is wrong, and I have been on the other side of this: a reviewer's or
builder's count gets copied into a test expectation and then asserted against
correct code. Worth correcting in the commit message if it is amended, not worth
a new commit of its own.

## Pre-existing observation (not this commit)

A whitespace-padded kind (`" SKILL "`) is refused as `unknown_kind: SKILL ` with
the spaces preserved, while bare `SKILL` passes. This is **not introduced here**:
`" MINE "` behaves identically. The gate compares the raw uppercased string with
no strip, for every kind. Recording it because nothing else does; it is a gate
robustness nit, not a SKILL-exemption issue, and out of scope for this change.

## Notes

- The builder's honesty here is worth recording: they reported that their own
  earlier mutation work could not have caught this because they had zero SKILL
  cases in the fixtures. That is exactly right — the shape was absent, so no
  mutant of the gate could redden. The three added tests close that gap.
- This defect was in code I passed three times. The reviews checked the gate's
  classifier and its fail-open behaviour against the shapes the tests contained;
  none of them asked whether a kind the *planner itself* emits was in the
  vocabulary the gate consults. That is the reviewer lesson from this round.

## Provenance

- Clean `git archive cf0360c` into a private temp dir, removed after
- Probes driven through the test module's own `_run_step`
- Mutants: anchors asserted unique; restore verified with `cmp`
- Suites run from file, rc captured directly (no pipe); planner-prompt test needs
  `PYTHONPATH=agent`, learned here

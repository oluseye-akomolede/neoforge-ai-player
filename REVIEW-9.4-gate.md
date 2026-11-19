# Review: a26b1c2 — 9.4 script-only gate fix (M3-1b cause B follow-up)

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-19
Rev under review: a26b1c2 (branch ship-ca27-harness)
Parent: f5136c0 (my PASS, review 9db9ffe)
Lead ruling: 9.4, 2026-11-19 13:25Z — script-only gate fix, NOT clearing lastProgress

## Verdict

**PASS.** The lead's four criteria are met and independently reproduced. The
builder did not implement the ruling's literal wording, and that was correct:
the literal wording is unimplementable. Evidence below.

## The builder departed from the ruling's text, and was right to

The ruling said to open the gate when the producer says the bot is idle —
"the top-level state field BotBrain:180 sets to idle".

**That field never reads `"idle"` in the payload.** Verified at a26b1c2:

- `BotBrain.java:180` — `map.put("state", activeBehavior != null ? activeBehavior.describeState() : "idle")`
- `BotBrain.java:29` — `this.activeBehavior = idleBehavior;` at construction
- `IdleBehavior.java:24` — `describeState()` returns `"Standing by"`
- `contract-v1.md:213` — the measured idle payload: `{"state": "Standing by", "progress": {"phase": "idle"}}`
- `BotBrain.java:96/:109/:121` restore `activeBehavior = idleBehavior` on every terminal path

`activeBehavior` is never null, so the `:180` ternary always takes the
`describeState()` branch and the literal `"idle"` is unreachable. A gate on
`state === "idle"` would never fire — the dead-guard class the script's own
health-guard comment documents, in the silent direction.

I checked this is not a distinction without a difference: `stateLine()` at
`:210` has the same ternary and DOES return `"idle"` when the field is null, but
it feeds only the overlay (`OverlayNetwork.java:1207`), never the HTTP payload
the script reads.

The builder implemented the ruling's stated QUESTION — "is a directive in
flight" — keyed on `directive.status`, and recorded the reasoning in both the
script and tasks.md. This is the right call and the lead should know the literal
instruction could not have worked.

## Criteria, reproduced

From a clean `git archive a26b1c2`, run with `PYTHONPATH=agent` and the real
runner (`agent-script-runner`):

| criterion | result |
|---|---|
| gate opens when idle | PASS |
| gate holds while a directive is ACTIVE | PASS |
| fixture covers done/failed/cancelled/active/never-run | PASS — one fixture each, plus unknown + unreadable |
| test RED on f5136c0 | PASS — 8 failures, set below |

Suite: **61 tests, OK, rc=0** across test_scout_script, test_script_tick,
test_scripts_configmap. Matches the builder's count.

### My own run, not their report

Red on the pre-fix tree (new tests, old scout.js — verified the two files differ):

    FAIL: test_completed_plan_opens_the_gate
    FAIL: test_every_terminal_status_opens_the_gate       (4 sub-cases)
    FAIL: test_the_state_field_is_not_the_gate
    FAIL: test_active_directive_still_holds
    FAIL: test_unknown_status_holds_rather_than_reading_as_idle

**The builder's accounting of which are behavioural is exactly right, and I
checked it rather than accepting it.** The last two fail only on the log-wording
assertion:

    AssertionError: 'ACTIVE' not found in 'scout: task phase pathing_to_cell, holding'
    AssertionError: 'PENDING' not found in 'scout: task phase mining, holding'

The old gate made the correct DECISION for both; only the new log line differs.
So the behavioural bites are 6, not 8, and the builder said so unprompted.

### Mutant

`TERMINAL_STATUSES = []`, anchor asserted at 1 before mutating (count printed as
1, exactly the guard against a no-op mutant that this builder has been bitten by
before): **6 red**, with `test_active_directive_still_holds` and
`test_unknown_status` correctly staying green. The mutant does not over-fire.

## The lead's reason for the ruling is preserved by construction

The ruling rests on `currentPhase()` feeding the in-game overlay, so the stale
phase is player-visible and clearing it would remove shown information.

`git diff f5136c0 a26b1c2 -- '*.java'` is **empty**. No mod file changed, so
`:180`, `:187` and `:217` serve exactly what they served before. The fix changes
the gate's decision and nothing about what is displayed. The overlay contract
the lead protected is untouched.

## Mirror

`deploy/agent-scripts.yaml` key value vs `agent/scripts/scout.js`, compared by
`yaml.safe_load` + sha256 of the key value (not a text diff): both 14333 bytes,
both `782c9910ad79b79f…`. Matches the builder's stated hash.

## Other checks

- Spec delta added; 9.2's "decision unchanged" superseded in place with the
  ruling and its rationale, not silently deleted.
- The two retyped line numbers the builder caught in their own delta
  (`currentPhase()` :211-218 → :213-219; "unreachable" without saying where)
  are corrected.
- `state` is logged, never tested — `test_the_state_field_is_not_the_gate` pins
  that a `"Standing by"` fixture still opens the gate, so no future test can
  reintroduce the dead guard.
- Fail-closed asymmetry verified by reading `_noDirectiveInFlight`: unknown
  status, missing directive and missing progress all return false (hold). Only
  positive evidence opens.

## Provenance

- Clean `git archive a26b1c2`; suites run by me with the real runner
- Pre-fix run used the NEW test file against the OLD scout.js (`cmp` confirmed
  they differ)
- Mutant anchored with a uniqueness assertion and the count printed
- No apply, no push, no exec, no secret values read

## Notes for the lead, not blockers

1. The ruling's literal wording could not work and the deviation is sound. If
   9.4 is recorded anywhere else using the "state field is idle" phrasing, that
   phrasing should be retired — it names a value the payload never carries.
2. The gate now opens after ANY terminated directive (FAILED and CANCELLED too,
   not only success), which is wider than the ruling's "completed" framing and
   is what the code does.

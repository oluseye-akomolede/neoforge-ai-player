# Review: A2 tasks.md reconciled, 17 -> 11 (`94ec07b`)

**Verdict: PASS with one non-blocking finding (F-1) and one routing note (F-2).
No defect in the commit.**

- Reviewer: minecraft-reviewer@minecraft
- Rev: `94ec07b3960c466e26a448042f84630ce62a68df` (branch `spec-a2-reanchor-cites`, parent `eae94c6`, not yet on `origin/main`)
- Scope: `openspec/changes/script-lookups-and-results/tasks.md` only, +28/-13
- Method: read every ticked task's own text, resolved every named test and line
  cite at the rev, recounted the `api.*` binding set deterministically in the
  runner repo, validated the change in a scratch worktree of my own.

## What I verified independently

| Claim | Result |
|---|---|
| Unticked boxes 17 -> 11 | **Confirmed** by count at parent and at `94ec07b`. |
| Single file, prose only | **Confirmed**: `tasks.md`, one parent (`eae94c6`). |
| `openspec validate --strict` valid, rc 0 | **Confirmed**, rc read directly (not through a pipe), in a scratch worktree checked out at the rev. |
| No test counts quoted in the diff | **Confirmed**: no `N tests`/`N OK` phrase in any added line. |
| `_plan_steps` guard at `agent.py:1313` | **Confirmed** verbatim at that line. |
| Three named tests exist | **Confirmed**, one definition each at this rev. |
| Class is `ScriptResultReachesTheSlotTest`, not `ResultDeliveryTest` | **Confirmed**: `:2183`; no `ResultDeliveryTest` exists. The row's own note about correcting this from memory is **true**. |
| `src/binding.js` binds **seven** `api.*` | **Confirmed**: `do, say, send, recall, result, remember, log`. |
| `MAX_HOST_CALLS` still 8 at `src/binding.js:32` | **Confirmed**. |
| "Six" was right before 3.1 added `result` | **Confirmed**: six methods at `0f11c90`, seven at `69006d1` and `bdaeeb7`. |

## The six ticks are sound

Ticking a box whose own text says WITHDRAWN / SUPERSEDED / OVERRULED / DEFERRED
is a consistent convention here: the box means **not outstanding**, not "done".
I checked that the line is drawn on evidence and not on convenience, because 3.9
says "Not done" and is ticked while 3.12 and 6.3 stay open:

- **3.9 (DEFERRED, ticked)** — the slot *rule* is implemented and tested
  (`test_a_result_from_a_superseded_goal_is_discarded_not_delivered`, present at
  this rev, and its own comment says it cannot yet fire in production). I traced
  the mechanism rather than trusting the prose: `_hold_script_result` binds
  `goal_id` from `_active_goal_id` **or** the same hold that `may_call` reads, so
  `pending[0] != goal_id` compares a value with itself and `goal-changed` is
  unreachable — exactly as the row states. A held script returns `SCRIPT_HELD`
  at `agent.py:3781`, before `st.tick()`, so a held script stores nothing. The
  deferral is accurate and the rule will activate unchanged.
- **3.12 (OPEN)** — the row says the two described tests do not exist. They do
  not: what exists is adjacent 3.5/3.6 behaviour, which does not drive two
  passes with a call live. Leaving it open is correct.

## Findings

**F-1 (scope call, worth a follow-up): `design.md:57` still says "only six host
functions exist"** and lists six names without `result`. At this rev the runner
binds seven. The row's own 6.2 correction establishes the count is wrong, and
`design.md` sits in the same change directory as the file the row edited — so
"outside this row's scope" is technically true (the row says `tasks.md` only)
but the inaccuracy is now documented-but-unfixed inside the change that will be
archived. Recommend fixing it in the same follow-up that fixes the live spec's
two "six api methods" mentions, before archive, so the archived change does not
record an untrue count in two places.

**F-2 (informational): 6.2's correction identifies the stale "six" in
`openspec/specs/bot-coded-agents/spec.md`, which is the live spec, not the
change.** Editing the live spec directly bypasses the delta gate; the correction
belongs as a spec delta in some change, or as an explicit owner-visible note —
not a silent edit of the live spec. The row did the right thing by flagging and
not fixing; recording it here so the eventual fix goes through a delta.

## Not verified

- I did not run the Python suites at this rev: the commit is prose-only, and the
  tests it names are only *cited* (to support a refusal), not changed. Running
  them would prove nothing about a diff that touches no code. If the lead wants
  a green run recorded alongside the archive, say so and I will run them.
- `94ec07b` is on a branch, not on `origin/main`. The lead's merge is the
  outstanding step for it to be "done" in the deployable sense.

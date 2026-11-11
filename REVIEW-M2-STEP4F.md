# Review — M2 step 4, fifth gate (`d75f30b`)

**Row:** `qitem-20261111124635-9baa2a708ca95045`
**Verdict: PASS on the `task` fix — I ran both mutants, both kill. HOLD on a
defect of the same class that the fix leaves standing: `scout.js` reads
`snapshot.health`, which does not exist, so its health guard has never fired
either.**

---

## 1. My error first — `tier=test`

I told the builder "`tier=test` is not a label anywhere in this plan" and, in the
same review, that the selector "matches nothing". The first clause was a grep of
the plan; the second was a claim about the **cluster**, which I cannot read from
this seat. Their pod label read — `{"app":"aibot-agent","tier":"test"}` — settles
it, and my instruction would have broken a command that works.

That is the same mistake I caught them making at `f836834`, with the polarity
reversed: I turned a scoped absence ("not in this document") into a global one
("not on this cluster"). Reverted in `8c22c69`; the selector stands as written,
and my edit is gone.

Two of my other rollback points were right and are kept: `kubectl cp -c agent`
(their invented-initContainer-doesn't-count argument is right — but a re-applied
manifest does, so the `-c` is correct as a rule) and the PVC sentence.

## 2. PASS — the `task` fix

`SnapshotCache.get` now calls `build_envelope(state, tick=tick,
task=state.get("task"))` (`snapshot.py:144`). That is the right place: the cache
is the only code that holds both the state and the envelope.

**Mutants, both mine, both killed:**

| mutant | result |
|---|---|
| drop `task=state.get("task")` (the original defect) | `Ran 21 tests, FAILED (failures=1)` — `test_envelope_from_the_cache_carries_the_running_task` |
| hardcode `task={"type": "STORE_ALL"}` | `Ran 21 tests, FAILED (failures=1)` — `test_envelope_task_is_none_when_nothing_is_running` |

The second is the one that matters and it is the control I would have asked for:
an always-reports-a-directive fixture would let a hardcoded task pass. They built
it unprompted, from the rule they wrote at `48b64cc` — two guards for every
predicate. That rule is now doing work neither of us had to argue for.

**Suite at `d75f30b` merged:** eight modules, `Ran 83 tests, OK`.

**§8.3.5 row 5 is a real addition, and it is better than my framing.** A dead
guard and a clean refusal are indistinguishable in the *agent* log — both show no
`not executed:` line. Their pass condition is the absence of a **runner tick for
that bot**, read from the runner's log. Row 2 could not have covered it because
row 2's pass case and row 5's pass case have the same agent-log signature.

## 3. HOLD — `snapshot.health` does not exist, so the health guard is dead too

Same class as the `task` defect, one level over, and the fix does not touch it.

`scout.js:26`: `var health = snapshot.health;`. The fact is at `state.health` —
`build_state` returns `{"health": status.get("health"), …}` inside `state`.
`snapshot.health` is `undefined`; the guard
`typeof health === "number" && health < 8` short-circuits on the first clause and
never holds.

**Verified by running the committed bytes** in a node VM against the real
envelope shape:

```
real, health 20        -> [{"kind":"STORE_ALL"}]
real, health 3         -> [{"kind":"STORE_ALL"}]   <- should hold, logs "too low"
real, task in flight   -> []                        <- the d75f30b fix, working
```

So a hurt bot (health 3) still proposes STORE_ALL. The comment above that guard
says the branch exists because "a starved or hurt bot acting on a stale plan is
how a bot walks into lava while it is already fleeing something." The branch has
never executed.

**Why no test caught it.** `test_scout_script.py`'s fixtures are literals like
`{"health": 20, "task": null}` — the flat object scout.js *wants*, never the
envelope it *gets*. `test_low_health_holds` passes because the fixture is the
shape the reader expects, not the shape the producer sends. That is the same
fixture-versus-producer gap that hid `act["directive"]` and the dead `task`
guard — the third instance of one defect in three files, each time surviving a
green suite.

**Before this commit I would have had to say the same of the `task` guard**: it
was fixed at the cache, which is right, but nothing in the plan's run would have
exercised the health branch. Row 5 was added for `task`; there is no row for
health, and a healthy Scout during the run means the difference is invisible.

## 4. A correction to my own §1 finding

I told them §1's diagram disagreed with the code, and recorded it as "the code
does not match contract §3". Reading the frozen contract
(`contract-v1.md:193-206`) shows I had the direction wrong:

| | facts live at | shape |
|---|---|---|
| `contract-v1.md` §3 (FROZEN, SHARED) | `state` | `{tick, server_ms, state, events, task}` |
| `M2-PLAN` §1 diagram | `bot` | `{"bot": {…}, "inventory": […], "nearby": {…}, "task": {…}}` |
| `build_envelope` (`snapshot.py:80`) | `state` | matches the contract |

The code matches the frozen contract. It is **the plan's diagram** that departs
from it — a leftover from an earlier draft. And the gap is wider than nesting:
scout.js reads `snapshot.health`, which is at neither level. I amended §1 to say
all three, rather than leaving a sentence that would have sent someone to "fix"
code that is already correct.

## 5. Still not verified by me

- The pod label — they read it, I cannot; I accept it and have removed my edit.
- Every other §8.3.1 cluster fact. §8.3.5 row 5 now depends on reading the
  runner's log, which is a read their run plan describes but that I cannot
  pre-verify from this seat.
- The initContainer manifest is written, not applied. Nothing built, nothing
  pushed, nothing deployed.

## Summary

| item | verdict |
|---|---|
| `task` passed into the envelope | **PASS** — mutant kills it |
| Idle control for the `task` guard | **PASS** — second mutant kills that too |
| §8.3.5 row 5 (runner-log absence) | **PASS** — better than my framing |
| `scout.js` health guard | **HOLD** — `snapshot.health` undefined; health 3 still stores |
| §1 diagram vs contract vs code | **CORRECTED by me** — the plan was wrong, not the code |
| My `tier=test` edit | **REVERTED by me** — correct conclusion, wrong operand |

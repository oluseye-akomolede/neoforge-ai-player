# Review — M2 step 4, seventh gate (`51d1aaa`)

**Row:** `qitem-20261111124635-9baa2a708ca95045`
**Verdict: HOLD. Two defects in the run plan's verification table, and one of them is
the same defect row 6 was just fixed for — one row up.**

Reviewed in a clean `git archive 51d1aaa` export. `openspec validate coded-agents
--strict` → **"Change 'coded-agents' is valid", rc=0, rev `51d1aaa` printed in the
same command.** `85f6809..51d1aaa` touches `M2-PLAN.md` only (+14/−1), so the code
I passed at `85f6809` is unchanged — 82 OK still stands for this rev.

I am **not** passing this plan for build yet. Both defects below are cheap to fix
and both would waste the run.

---

## 1. Row 6 is fixed correctly — PASS

`51d1aaa` replaces the unobservable log condition with *no runner tick for Scout,
read from the RUNNER's log*, and adds a rationale block (1155-1190) recording why,
including that plumbing wire `logs` into the tick tuple is its own slice. That is
the right call and the right record. **Row 6: PASS.**

---

## 2. HOLD — row 2 asks for a `COMPLETED` line that is never printed

Row 2 (`M2-PLAN.md:1152` at `51d1aaa`):

> **Agent** log: `[Scout/script] dispatch: STORE_ALL {...}` followed by a
> `COMPLETED STORE_ALL` return, and **no** `[Scout/script] not executed:` line

The first and third clauses are observable. **The middle one is not.**

`_l3_orchestrator_dispatch` does return `f"COMPLETED {params['type']} ..."`
(`agent.py:1024`), but `_run_script_tick` (`agent.py:2641-2651`) prints the
dispatch result **only when it starts with `FAILED`**:

```python
print(f"[{self.name}/script] dispatch: {kind} {directive}")
result = self._l3_orchestrator_dispatch(directive)
if isinstance(result, str) and result.startswith("FAILED"):
    print(f"[{self.name}/script] not executed: {result}")
    continue
ran += 1
```

On success the string goes to `telemetry.push` (`agent.py:1025`), which POSTs it
to `MOD_API_URL/telemetry/event` on a daemon thread (`telemetry.py:37`) — **not to
the agent log**, and the plan names no telemetry reader anywhere in §8.3.

**Observed, not inferred.** Running the suites and filtering for the two strings:

```
dispatch: EQUIP_ALL {'kind': 'EQUIP_ALL'}
dispatch: STORE_ALL {'kind': 'STORE_ALL', 'x': '10', 'y': '64', 'z': '10'}
dispatch: STORE_ALL {'kind': 'STORE_ALL'}
dispatch: DROP {'kind': 'DROP', 'target': 'dirt'}
```
— six `dispatch:` lines, **zero `COMPLETED`**.

An operator running row 2 finds `dispatch:` and no `COMPLETED`, concludes the
dispatch was refused, and records a failed run against working code. This is
row 6's defect exactly: a required string the agent never emits. I held row 6
for it at `85f6809`; the same sentence is still in row 2 one line up.

**Fix:** delete the `COMPLETED` clause. Row 2 already has a complete, observable
pass condition in its other two clauses — `dispatch:` present **and**
`not executed:` absent. That pair distinguishes "dispatched and ran" from
"refused before dispatch" and from "dispatched and FAILED", which is everything
the row is for. If the operator wants the success string itself, it is readable
at the dashboard's telemetry stream, and that should be named as a source or
left out — not cited from the agent log.

---

## 3. HOLD — line 712 attaches the new revision to the old rev

`M2-PLAN.md:712` at `51d1aaa`:

> which for `scout.js` at `d75f30b` is `823920fd7277b98b`

Measured across the revs:

| rev | `sha256(scout.js)[:16]` |
|---|---|
| `80aadcb` | `7fdbad9076381f43` |
| `d75f30b` | `7fdbad9076381f43` |
| `85f6809` | `823920fd7277b98b` |
| `51d1aaa` | `823920fd7277b98b` |

`823920fd7277b98b` is `85f6809`'s hash. The revision was updated when the health
guard was fixed; this sentence kept the old rev. The `85f6809` fix was
`state.health` (one identifier), so `d75f30b`'s `scout.js` is the pre-fix script
and hashes to `7fdbad90`.

Low severity on its own — the *value* the operator compares against is correct,
and it appears correctly three times elsewhere. But this is the sentence that
tells the operator where the number comes from, and its citation is wrong in the
same way `2d412df` fixed the store citation. A number without a true provenance is
the thing §8.3 is built to prevent.

**Fix:** `d75f30b` → `85f6809` at line 712.

---

## 4. Checked and correct at this rev

- **Row 1** cites `823920fd7277b98b` — correct, matches `85f6809` and `51d1aaa`.
- **Rows 3, 4, 5** are observable as written; row 5's basis (runner log absence)
  is sound, and its rationale block is what makes it reusable.
- **Strict validation passes at the rev**, with the rev printed in the same command.
- **Plan-only diff** — no code changed since the `85f6809` pass, so no re-run of
  the suite or mutants is owed.

---

## 5. What I did not verify

- Every cluster fact. No cluster access from this seat.
- The initContainer manifest: written, not applied, not exercised.
- The runner end-to-end: I traced `logs` and `COMPLETED` through the agent side
  and observed both absent from stdout by running the suites, but I have not run
  the runner against a live agent.

Nothing built, nothing pushed, nothing deployed.

| item | verdict |
|---|---|
| Row 6 (health guard, runner-log basis) | **PASS** — fixed correctly, rationale recorded |
| Row 1 revision citation | **PASS** — recomputed |
| Row 2 `COMPLETED` clause | **HOLD** — never printed; success goes to telemetry |
| Line 712 rev/revision pairing | **HOLD** — `823920fd…` is `85f6809`'s, not `d75f30b`'s |
| `openspec validate --strict` at `51d1aaa` | **PASS** — valid, rc=0 |
| Code unchanged since `85f6809` | **PASS** — plan-only diff |

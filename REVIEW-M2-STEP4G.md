# Review — M2 step 4, sixth gate (`85f6809`)

**Row:** `qitem-20261111124635-9baa2a708ca95045`
**Verdict: PASS on the health-guard fix and the fixture rewrite. HOLD on run-plan row 6 —
it requires a log line the agent does not print.**

Reviewed at `85f6809` in a clean `git archive` export (`/tmp/rv85`), not in my worktree:
my branch carries my own review commits, so `git merge --ff-only` refuses and a
worktree test would have measured the wrong tree. Everything below is from the export.

---

## 1. First, an error of mine caught by the instrument

My first mutant A run printed `Ran 5 tests ... OK`, which would have meant the
mutant survived. It was an artefact: the worktree was at `21ec724` (my review
commit on `d75f30b`), which **does not contain `85f6809` at all**, and my command
sequence restored the file before measuring. The tell was `5 tests` against the
builder's `6` — a count mismatch is a tree mismatch, not a mutant result.

This is `validate-in-the-worktree-that-holds-the-rev` again, and the second time
today I have nearly reported a false survivor. The export fixed it: baseline
**`Ran 6 tests, OK`**, and every mutant below is run there.

---

## 2. The fix — PASS

`scout.js:35` now reads `state.health`; `SnapshotCache` supplies the envelope with
`task` threaded through. Verified at the boundaries the predicate names:

| envelope | actions | `api.log` |
|---|---|---|
| health 20, no task | `[{"kind":"STORE_ALL"}]` | – |
| health 8, no task | `[{"kind":"STORE_ALL"}]` | – (8 is not `< 8`) |
| health 7.9, no task | `[]` | `scout: health 7.9 too low, holding` |
| health 3, no task | `[]` | `scout: health 3 too low, holding` |
| health 0, no task | `[]` | `scout: health 0 too low, holding` |
| health 20, task set | `[]` | – |

Both guards live, both boundaries correct, and they do not mask each other.

**Mutants, run by me in the export:**

- **A — restore `snapshot.health`:** `Ran 6 tests ... FAILED (failures=3)`. Matches
  the builder's report exactly.
- **B — make `_envelope` emit the flat shape:** `FAILED (failures=2)`, and the
  cache test alone stays **OK**. That is the property that matters: the
  envelope-through-the-cache test constructs its own input, so the helper-level
  and cache-level guards cannot cover for one another. Builder's claim confirmed
  by direct measurement, not accepted on description.

**Merged suite at `85f6809`:** `Ran 82 tests ... OK` (seven modules, explicit names).

`discover -s agent -p 'test_script*.py'` reports `FAILED (errors=1)` — that is
`test module: dashboard` / `No module named 'uvicorn'`, the known seat gap, not a
defect in this change. The explicit-module tally above is the real one.

**Revision claim re-checked independently:** `sha256(scout.js at 85f6809)` is
`823920fd7277b98b`, and that literal appears 3× in the plan at the same rev.
The stale `7fdbad9076381f43` is retained only in the sentence that names it as
superseded, which is correct.

---

## 3. HOLD — row 6 asserts a log line that is never printed

Row 6 (`M2-PLAN.md:1158` at `85f6809`) reads:

> the agent log carries `[Scout/script] scout: health N too low, holding`

The script does call `api.log("scout: health " + health + " too low, holding")` and
I confirmed the string is produced. But it does not reach the agent log:

1. `api.log` is not an action and not stdout — in the runner
   (`src/binding.js:27`) it "rides the tick as the `memory_out` and `logs` result
   fields".
2. `ScriptTick.tick()` (`script_tick.py:100-149`) returns
   `(handled, actions, refusals, detail)`. **`logs` is not in that tuple and is
   never read from `result`.**
3. `bind_actions` returns only `(bound, refusals)`.
4. `agent.py:2638-2660` prints eight `[<bot>/script]` lines, and every one is
   derived from actions, dispatch results, or the caught exception. There is no
   path from wire `logs` to stdout.

So `[Scout/script] scout: health 3 too low, holding` will not appear in the agent
log on the run, however well the guard works. An operator following row 6 gets a
red row against a correct fix — and given row 6's own history (it was written
because a dead guard and a clean refusal look alike), a red row there invites
exactly the wrong conclusion.

**This is not a defect in `85f6809`.** The guard, its tests, and the revision are
all right. It is a defect in the **run plan**, which is the artefact the operator
executes.

**Fix — either, and the first is smaller:**

- **Drop the log condition from row 6.** The row already has a sufficient,
  observable pass condition: *no runner tick for that bot*, read from the runner
  log, plus the absence of `dispatch:`/`not executed:`. That distinguishes a
  firing guard from a dead one without the unprinted string.
- **Or make the string observable.** Plumb `logs` from `result` through
  `tick()` and print it — a real change to the tuple contract and its callers,
  and it makes every future script `api.log` visible, which the run plan's other
  rows would then want to use. Bigger than this gate needs.

I recommend the first. The guard's evidence already exists on the runner side.

**Note on my confidence:** I traced `logs` to the runner's wire format and read
`tick()` and the print block in full. I did not run the runner end-to-end, so I
have not observed a real `logs` field on the wire. The claim above is that no
code path in `agent/` reads it — which I did establish by grep over
`script_tick.py`, `script_client.py` and the print block — not that the runner
fails to send it.

---

## 4. What the builder got right that I should name

- **The test was the fix, and they said so before writing it.** The failing-first
  evidence (`[{'kind':'STORE_ALL'}]` at health 3, observed before touching the
  script) is what separates a test from a restatement. I have rejected the
  restatement version earlier in this run.
- **They corrected my §1 amendment.** I told them at 13:03Z the code diverged
  from contract §3; at 13:04Z I corrected myself and they had already recorded my
  first, wrong version. They fixed it and listed the three shape facts
  separately. Taking a reviewer's correction twice in one exchange is the harder
  direction.
- **Mutant B's design** — leaving the cache test green — is the "two guards for
  every predicate" rule applied to two *different* guards rather than a check and
  its control. Worth keeping.
- **The tally** ("all three were mine", with the common move named) is accurate.
  I supplied the generalisation; they supplied the three instances. Neither of us
  found all three alone.

---

## 5. Not verified by me

- Every cluster fact (namespace, pod label, `PROFILES_DIR` on the live pod, the
  deployed image's provenance). No cluster access from this seat — the builder
  read the pod label; I did not.
- The initContainer manifest: written, not applied, and not exercised.
- The runner end-to-end (see §3).

Nothing built, nothing pushed, nothing deployed.

| item | verdict |
|---|---|
| `scout.js` health guard reads the right operand | **PASS** — boundary sweep, all six cases |
| `task` guard still live after the change | **PASS** — holds at health 20 with a task |
| Mutant A (restore `snapshot.health`) | **PASS** — failures=3, mine |
| Mutant B (flat `_envelope`) | **PASS** — failures=2; cache test green by design |
| Fixture rewrite / failing-first evidence | **PASS** — the generalising fix |
| `script_revision` `823920fd7277b98b` | **PASS** — recomputed at `85f6809`, 3 citations |
| Merged suite | **PASS** — 82 OK from the export |
| Row 6 log assertion | **HOLD** — string never reaches the agent log |

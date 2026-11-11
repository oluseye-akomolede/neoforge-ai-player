# Review — M2 step 4, fourth gate (`a43145d`)

**Row:** `qitem-20261111124635-9baa2a708ca95045`
**Verdict: PASS on the routing fix and the PROFILES_DIR guard — both mutants run
by me. HOLD on one defect the plan's own code proves: `snapshot.task` is
always `null` where scout.js reads it, so the script can act on a tick when a
mod directive is already in flight.**

Range: `a43145d` merged into `minecraft-wt-qwen` (`578f182`), 5 files, 114 tests
reported. I ran them.

---

## 1. PASS — routing through `_l3_orchestrator_dispatch`

`_run_script_tick` now calls `_l3_orchestrator_dispatch(directive)` (`:2651`),
which handles both vocabularies: EQUIP/EQUIP_ALL → `api.equip_all`, DROP/DISCARD
→ slot resolution + `api.drop`, VAULT_* → `api.vault_*`, PROVISION_TERMINAL and
ASK_PLAYER special-cased, and everything else mapped `kind`→`type` into
`_run_directive` (`:1012`). Every return path is a `COMPLETED`/`FAILED` string,
so the `startswith("FAILED")` test in the tick is sound and no exception escapes
into the loop.

The refusal handling is the part that matters: `ran == 0` after the loop returns
`False`, so the planner gets the tick. That is the 7.2 guarantee restored at the
level where it had broken.

**Mutant (mine):** reverting the dispatch line to
`self._run_directive({"type": directive["kind"]})` → `test_agent_script_branch`
`Ran 9 tests, FAILED (failures=4)`. Matches their report. Tree restored.

One change of shape worth noting, not a defect: the old code printed `dispatch:`
for the first action only; it now prints for **every** action. That is what makes
§8.3.5 row 2 ("`dispatch:` followed by `COMPLETED`, and **no** `not executed:`")
checkable per action rather than per tick, and it means a mixed tick is now
visible line by line. Better than what I asked for.

## 2. PASS — `PROFILES_DIR`, guard and all three cells

`load_profiles()` (`:3314`): `os.getenv("PROFILES_DIR") or <image path>`. Unset
and `""` both fall through to `dirname(__file__)/profiles`, which is today's
behaviour, so prod is untouched. Verified each cell by hand as well as through
the test: set → my tempdir's single profile; unset → the five image profiles;
empty → the five image profiles.

**Mutant (mine):** hardcoding the image path (dropping the `getenv`) →
`test_profiles_dir Ran 3 tests, FAILED (failures=1)`. This was the cell that had
no guard for a whole review cycle and it now has one with a control that can
fail. Tree restored.

**Suite, run by me at `578f182`:** the eight real modules (`test_action_binding`,
`test_agent_script_branch`, `test_profiles_dir`, `test_scout_script`,
`test_script_client`, `test_script_tick`, `test_scripts_configmap`,
`test_snapshot`) → `Ran 81 tests, OK`. `discover` also picks up
`agent/dashboard/` and errors on `uvicorn` in this seat; that is an artefact of
discovery, not of the change, and naming the modules explicitly gives the real
count.

## 3. HOLD — `snapshot.task` is always `null` where the script reads it

scout.js guards against acting underneath a running job:

```js
if (snapshot.task) { return []; }
```

`snapshot` is the **envelope** (`script_tick.py:150` → `SnapshotCache.get`).
`build_envelope` puts `"task": task` at the top level and `SnapshotCache`
constructs it with **no `task=` argument** (`snapshot.py:137`), so
`envelope["task"]` is the default `None` on every tick.

The directive the bot is actually running is `state["task"]` —
`build_state` sets `"task": directive` from `api.get_directive` (`snapshot.py:76`).
So the field scout.js reads is `null` while the field that holds the running
directive sits one level down in `state.task`.

**Demonstrated, not inferred** — scout.js executed in a VM under both shapes:

```
plan-doc shape (task nested): [{"kind":"STORE_ALL"}]   <- acts
with a running task:          []                        <- holds
```

Under the real envelope the first line is what happens *even when a directive is
in flight*. The guard is dead. Two consequences:

1. **The M2 run can act on a tick when a directive is already running.** The
   STORE_ALL then fails ("already has a directive") — a `FAILED`, logged as
   `not executed:`, and the planner falls through. Not silent, which is why this
   is a HOLD and not a blocker on the build. But the third §1 scenario ("no
   action is taken on a tick with a task already in flight") is not met, and the
   run would not reveal that: a `not executed:` line reads as a refusal, not as
   a guard that never fired.
2. **§1's snapshot contract and the code disagree, and the test enforces the
   code.** The plan's frozen shape (`M2-PLAN:48-52`) is
   `{"bot": {...}, "inventory": [...], "nearby": {...}, "task": {...}}` — task
   nested inside a `bot`-headed object. The implementation is
   `{tick, server_ms, state, events, task}` with task at the top level.
   `test_snapshot.py:149-166` asserts the implementation's shape and passes a
   `task=` the production cache never passes. **So the test that pins this
   contract exercises a payload no caller can produce** — the same fixture-vs-
   producer gap that let the `act["directive"]` defect through, in the file that
   was reviewed on the same day.

**Fix, either way, and the choice is the builder's:** set
`snapshot.task` on the envelope from `state["task"]` (one line in
`SnapshotCache.get`), or change scout.js to read `snapshot.state.task`. Then add
a test that builds the envelope **through `SnapshotCache`** — the production
path — with a live directive and asserts the script holds. I am not prescribing
which, but the contract in §1 has to match whichever is chosen.

## 4. Plan defects I fixed in my own commit, not held against them

The rollback block (§9) had four commands that cannot work as printed:

| printed | why it fails |
|---|---|
| `cp "$POD:..."` / `cp ./evidence/... "$POD:..."` | `kubectl cp` requires `-c` when the pod has more than one container; the plan adds an **initContainer**, so after step 2 the pod has two and every later `kubectl cp` errors. Removed initContainers do not count, but a re-applied manifest does. |
| `-l app=aibot-agent,tier=test` | the only selector anywhere in the plan is `app=aibot-agent` (§8.3.1, and the §8.3.2 seed manifest). `tier=test` is invented here and matches nothing — the command would resolve `POD=` empty and the next three lines would fail *after* `git revert` had already run. |
| "`scout.json` on the `agent-data` PVC" | after this change it is on the `/srv/aibot-profiles` emptyDir. The PVC sentence is the pre-change world. |

All four are in my commit (`578f182` + the fix commit), with the `-c agent` and
the selector corrected, and `openspec validate coded-agents --strict` still
valid.

**What passed in the plan:** the initContainer manifest with `cp -an` and the
stated reason (emptyDir survives a container restart but not pod recreation, so
`-n` is what makes "restart the pod" and "keep the edit" compatible) — that
resolves the contradiction I raised, and step 4 now requires the sha256 recheck
after the restart. `PROFILES_DIR` set in step 2 while no profile names a script
keeps the restart inert, which is the ordering argument holding. Mount moved to
`/srv/aibot-scripts` for the `COPY . .` shadowing reason. `_float_env` recorded
as a passenger, not an M2 deliverable.

## 5. Still not verified by me

- Every cluster fact in §8.3.1: the deployed digest, the `d45751d` derivation,
  1/1, the ConfigMap's absence, the pod's env. No cluster access from this seat.
  Their own caveat — the blob match identifies the source commit, not that the
  image came from a clean tree — is correctly scoped and I am not holding for it.
- The initContainer manifest is written, not applied. Nothing deployed.
- `agent/dashboard/` under `unittest discover` in a seat without `uvicorn` —
  unrelated to this change, but it will bite whoever runs discovery here.

## Summary

| item | verdict |
|---|---|
| Routing via `_l3_orchestrator_dispatch` | **PASS** — mutant kills it, 4 failures |
| Refusals fall through to the planner | **PASS** — `ran == 0` → `False` |
| `PROFILES_DIR` + set/unset/empty tests | **PASS** — mutant kills it, 1 failure |
| 8 modules green on `578f182` | **PASS** — `Ran 81 tests, OK` |
| `snapshot.task` guard in scout.js | **HOLD** — always `null`; demonstrated in a VM |
| §1 snapshot contract vs code vs test | **HOLD** — same defect; test pins an unfeedable payload |
| Rollback commands | **FIXED by me** — `-c agent`, selector, PVC sentence |

Nothing built, nothing pushed, nothing deployed. No secret value printed.

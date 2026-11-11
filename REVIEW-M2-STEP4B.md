# Review — M2 step 4 (transport fix + TEST run plan)

**Row:** `qitem-20261111124635-9baa2a708ca95045`
**Verdict: PASS on `4035605` and `2d412df`. HOLD on `a9e23c8` for three gaps against
the lead's conditions.**

Range reviewed: `60f8a60..2d412df`. Tree clean. 74 tests OK from `agent/`.

---

## 1. `4035605` — the transport fix, and it was the worst defect of the run

The builder found this while fixing my skip finding, in the file I had just
reviewed. Worth stating plainly: **I reviewed `script_tick.py` at `f2e003f` and
did not see that its transport pointed at the game mod.**

The defect: `ScriptTick` defaulted `post` to `api._post`, which prefixes
`MOD_API_URL`; `agent.py:2652` constructs it with `post=None`. Every script tick
went to the mod. The mod answers JSON, so `call_runner` reads the reply as a
script result or a fallback — **the run would have looked handled with the runner
never involved.** Nothing in `agent/` read a runner URL at all.

That is the inert-gate class in its worst form: the gate *was* the transport, and
it was answering.

**Verified, not taken on report:**
- `_default_transport()` reads `SCRIPT_RUNNER_URL` only; empty → `None` → the
  tick returns `False` and the planner runs. It cannot fall back to `api._post`.
- **Mutant (mine):** replacing `SCRIPT_RUNNER_URL` with `MOD_API_URL` in
  `_default_transport` → **2 failures**. The test catches the transport being
  pointed back at the mod. Tree restored, `git status` clean.
- **Mutant (mine):** blocking `yaml` with a `MetaPathFinder` (block confirmed) →
  `ran=2 skipped=0 failures=2 successful=False`. The drift test fails rather than
  skips. The `setUp` form they chose is the right one: adding PyYAML as a dep is
  how the test gets disabled by whoever next builds the image.
- `call_runner` passes `timeout=SCRIPT_TIMEOUT` explicitly (`:161`), so the
  `timeout=5` default inside `_default_transport` is never used on this path.
  Checked because it is the same shape as the override I found at `37d36c5`.

---

## 2. `2d412df` — the store citation correction is honest and complete

It names the error ("2026-07-16 archive", written from memory), gives the real
record (`agent_trajectories/trajectory-2026-08-14.jsonl:2`), and states the three
reasons it is not evidence — one record, three months stale, and `model` is
`qwen2.5:14b` not the `qwen3-coder:30b` the profiles name, so it is not even the
current planner.

That last point is the builder finding something weaker than I had flagged. My
note said only "unverified"; reading the record showed it does not speak to the
current planner at all. Recorded as **consistent with** the structural argument,
never as the observation carrying it, with the live check moved to the 8.2 run —
and the plan forbids reshaping the test on the fly if the run disagrees. That is
how a pre-registered expectation should read.

**Not verified by me:** the record itself. No cluster access from this seat.

---

## 3. HOLD — `a9e23c8` does not meet three of the lead's conditions

### 3a. The forbidden targets are never named (lead item 2)

The plan uses `minecraft-test` / `aibot-agent-test` throughout, but **never says
what must not be touched**. Grepping the plan for `mindcraft`, prod targets or a
prohibition finds nothing.

The lead asked for this explicitly: *"NOT minecraft/aibot-agent (prod) and NOT
mindcraft/aibot-agent (stale, 0/0)."* A plan that omits the wrong target is
weaker than one that forbids it — an operator choosing a context has no
in-document signal that `minecraft` is a trap, and a wrong context here reaches
production bots.

**Fix:** a named "must not touch" block in §8.3, with the current context quoted
in every `kubectl` invocation so the target is visible in the transcript.

### 3b. The image story is stated but its consequence is not (lead item 3)

Two different questions are conflated in the document:

- Line 693: *"Edits are a `kubectl apply` of the ConfigMap plus a pod restart —
  no image build."* True of **script storage** (decision 3: ConfigMap over
  baked-in).
- The lead's ruling: **build and push a new image**, because the deployed one
  predates `4035605`.

A reader taking line 693 at face value concludes no build is needed and the
transport fix is inert on the cluster. The plan must say: script storage needs no
rebuild; **the agent code does**, and the deployed image cannot work.

**What else the new image changes for the other four bots — checked in the
code, not claimed.** Everything since the step-3 base is additive and
script-path-local:

```
agent/action_binding.py    +129   (new)
agent/config.py              +8   (SCRIPT_RUNNER_URL)
agent/script_client.py      +98   (new)
agent/script_tick.py       +158   (new)
agent/snapshot.py          +156   (new)
agent/agent.py              +84   (three hunks; no deletions)
```

No existing module was modified; the `agent.py` diff has **no `-` lines**. The
one shared-loop change is the call at `:2671`. For a bot with no `script` key:

- `_get_script_tick` sets `_script_loaded = True` and returns `None` — the
  profile lookup happens **once per bot**, not per tick;
- `_run_script_tick` returns `False` on `st is None` with no print, no
  allocation and no HTTP.

So the four other bots pay one dict lookup at startup and one boolean per tick.
**I found no changed behaviour for them, and that is the lead's item 3
answered** — but it is answered in this review, and it belongs in the plan where
the deployer will read it.

### 3c. Lead item 4 — the profile rollback is described, not specified

§8.3.2 says the edit is pod-local and §8.3.3 step 4 says to "record the exact
file edited and its before/after `script` key". The lead asked for more: **copy
the original off-pod first**, commit the edited profile text as evidence, and the
rollback must restore that file.

`agent-data` is a PVC, so a pod restart does not lose it — but a bad edit to
`profiles/Scout.json` is not recoverable from git, and §8.3.6 says so without
giving the recovery step. The rollback section must name the file and the restore
command.

---

## 4. What the plan gets right, and is better than my own advice

- **Order pays the restart risk while the feature is provably inert** (§8.3.3):
  ConfigMap → mount+env → confirm 1/1 → then the profile. The restart happens at
  the one moment no bot can be running a script. That is the right sequencing and
  I would not have thought of it.
- **The negative control is specified as two required runs with the baseline
  named** (§8.3.4), and the control must not stop the shared runner.
- **The invocation hazard is recorded** (§8.3.6) — the suites run from `agent/`;
  from the repo root `agent` resolves to `agent.py` because there is no
  `__init__.py`. I raised it as a minor; they put it where a run plan needs it.
- **§8.3.7 does not overclaim:** the raw-model form is untraced, and if both runs
  match the reader is told to check the runner log before concluding failure.

---

## 5. Smaller items, not blocking

- **`agent/__init__.py` absence** is the root cause of the invocation hazard.
  Adding an empty file would make `unittest agent.test_x` work from the root, but
  it would also change how every module imports — that is a separate change, not
  a rider on this one.
- The multi-step config the run plan shows (`Decision 3`) still describes
  ConfigMap-only storage; once the image rebuild is added it should say the
  rebuild is for `4035605`, not for scripts.

---

## Summary

| item | verdict |
|---|---|
| `4035605` transport fix | **PASS** — mutant kills it; cannot reach the mod |
| `4035605` drift test fails without PyYAML | **PASS** — verified by blocker |
| `2d412df` citation correction | **PASS** — honest, and weaker than claimed |
| `a9e23c8` lead item 2 (forbidden targets) | **HOLD** — not named anywhere |
| `a9e23c8` lead item 3 (image / other bots) | **HOLD** — answer is in this review, not the plan |
| `a9e23c8` lead item 4 (profile rollback) | **HOLD** — restore step not specified |
| `a9e23c8` ordering, control, hazards | PASS — better than my own advice |

Nothing deployed. No secret value printed; the runner URL is a service name.

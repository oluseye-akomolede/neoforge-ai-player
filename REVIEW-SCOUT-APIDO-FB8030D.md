# Review — fb8030d (scout.js acts via `api.do`; test runs the real engine)

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-13
Verdict: **PASS.** All four requested checks hold, and the mutation pair
re-derives to the claimed numbers.

Reviewed at `fb8030d` (fix in `096c1e9`, run plan in `fb8030d`).
`git diff --stat 096c1e9 fb8030d` → one file, 96 insertions
(`RUN-PLAN-scout-api-do.md`), matching the claim that the second commit is
plan-only.

`openspec validate coded-agents --strict` → `Change 'coded-agents' is valid`,
run inside a clean `git archive fb8030d` export, not my worktree.

**Why this defect mattered.** The runner ignores a script's return value and
collects actions only from `api.do`. `scout.js` returned its action from
`tick()`, so the action was discarded on every tick and the bot was never asked
to do anything — while the test was green throughout, because it rewrote the
source into a shape it could read and stubbed the channel under test. This is
the strongest instance of the run's recurring class: a fixture confirming the
consumer rather than the producer.

---

## 1. `scout.js` emits via `api.do` and retains every guard

Compared old and new by inventory, not by eye:

| guard | old | new |
|---|---|---|
| no snapshot (`typeof snapshot === "undefined" \|\| === null`) | `return []` (`:18`-20) | `return;` (`:18`-20) |
| low health (`typeof health === "number" && health < 8`) | `return []` (`:36`-38) | `return;` (`:36`-38) |
| busy bot (`task && !(task.progress && task.progress.phase === "idle")`) | `return []` (`:64`-65) | `return;` (`:64`-65) |

Three guards, same conditions, same order, same `api.log` lines. Only the
return form changed, and the action is now `api.do("STORE_ALL", {})` at `:97`.
**No guard weakened, added or lost.** The busy-bot guard still discriminates on
`progress.phase === "idle"`, which is the shape I reviewed against
`contract-v1.md` earlier, so the two reviews agree on the envelope.

The coordless `STORE_ALL` form — which 8.2 pins — is preserved deliberately, and
the comment now records *both* why it goes through `api.do` and why it carries
no coordinates. It lost none of the original reasoning.

---

## 2. The test runs the committed bytes unmodified; no stub survives

This was the check that mattered, so I tested it by execution, not by reading:

```
' src.replace', 'return tick()', 'new Function', 'api.do =':
    all 0 hits in the test's EXECUTABLE BODY (docstring excluded)
```

The docstring contains both phrases — it quotes the old `src.replace` to explain
what was removed — so I split the file at the closing docstring and searched the
remainder. That split is what makes the zero meaningful; a whole-file grep would
have returned 4 and told me nothing about whether the code runs.

From the executable body, independently confirmed:

- `_DRIVER` reads the script with `readFileSync(scriptPath, "utf8")` — the
  committed bytes, not a rewritten copy.
- `new Sandbox(rt, { tickCpuMs: 250, bindApi: true })` from the runner's own
  `./src/engine.js`; `bindApi: true` installs the **real** `api`, so nothing
  imitates the channel.
- Assertions read `box.tickState` — the collector `worker.js` serialises as
  `actions` — not the return value.
- The one `.replace()` (`:133`) substitutes the driver template's
  `SOURCE(snapshot)` placeholder. It does not touch the script.

**The negative test fails for the right reason.** `test_a_returned_array_never_
calls_api_do_and_yields_no_actions` writes an old-shape script and asserts the
engine collects `[]`. It is properly paired with
`test_action_is_emitted_through_api_do_not_a_returned_array`, which asserts
exactly one action arriving with `call == "do"` *and* `host_calls >= 1`. Neither
can pass vacuously while the other holds: the positive pins that the collector
works, the negative pins that returning is not the channel.

---

## 3. Mutation pair — re-derived, not taken

Built a clean export of `fb8030d`, then replaced only
`agent/scripts/scout.js` with `096c1e9^`'s version. Confirmed the substitution
by content: `sha256 = 838efd89…` on both the extracted file and
`git show 096c1e9^:agent/scripts/scout.js`.

| script under test | result | rc |
|---|---|---|
| old (`096c1e9^`) | 4 failures | **1** |
| new (`fb8030d`) | 9/9 pass | **0** |

The failure is for the right reason, quoting the run:

```
Lists differ: [] != [{'seq': 1, 'call': 'do', 'directive': 'STORE_ALL', 'args': {}}]
```

The old script emitted `[]` against the real collector, which expected the
`STORE_ALL` directive. That is the production bug reproduced, not an incidental
error. The builder's claimed 4-fail/9-pass is correct.

---

## 4. Spec, run plan, digests, restart

- **Requirement** — `A Script Acts By Calling The API, Never By Returning` sits
  beside `Scripts Act Only Through The Existing Bot Actions`, which is unchanged.
  Four scenarios, each mapping to a test I can name (§2 and §3 above). Nothing
  is removed from the neighbouring requirement.
- **Digests are computed, not typed.** Verified both against the artefacts
  directly: old `838efd89…` = sha256 of `096c1e9^:agent/scripts/scout.js`; new
  `1824967e…` = sha256 of `fb8030d:agent/scripts/scout.js`. Both match exactly.
- **The restart requirement is justified from the code.** `agent.py:2797` is
  `if self._script_loaded: return self._script_tick` and `:2799` sets the flag —
  read once, never re-read. So a ConfigMap-only update changes nothing a running
  pod sees. The plan's reasoning is correct, not decorative.
- **The rollback is complete**: restore the backup, restart, await
  `rollout status`, then confirm by re-reading the digest — with the right rule
  that completion is *the mounted file matching*, not the apply returning.
- **The ConfigMap carries the fix**: `deploy/agent-scripts.yaml:131` has
  `api.do("STORE_ALL", {})` and the bare `return;` guards. Manifest and source
  commit agree, so the deployed artefact is the reviewed one.

---

## 5. Suite, and why I am not calling it a clean 102

`Ran 103 tests ... FAILED (errors=1)`, the single error being
`dashboard` → `ModuleNotFoundError: No module named 'uvicorn'` from
`agent/dashboard/server.py:16`. That is a missing dependency in **my**
environment, reproduced identically by the builder before this change, and it is
not an assertion failure. Excluding it, 102 pass — consistent with the claimed
baseline 100 → 102.

I am stating the raw result rather than quoting "102 OK" as if the run were
clean, because the distinction between an import error in my environment and a
failing test is exactly the kind of thing that gets lost when a number is
repeated.

---

## 6. What I did not verify

The live run. Steps 5-6 of the plan — the first loop-driven evidence and the
re-taken control baseline — cannot be verified from here; they are what the run
itself is for. The plan is explicit that if step 5's tick does not appear it is a
finding, not a retry, which is the right instruction.

I did not build, push or apply anything, and I did not run the live ConfigMap
apply. The digests above are computed over the committed artefacts, which is a
different question from what is currently mounted on the cluster.

---

## Notes

- The builder's own `exitCode`-vs-`signalCode` bug in the sibling test is
  correctly fixed; I measured that a SIGKILL'd child reports `exitCode = null`,
  so an `exitCode` assertion would have read a kill as a success.
- The plan independently records the `SEARCH_AND_STORE` planner defect I
  reported on row 55b0b5ec, on its own row (`b3150175`), and notes it "will make
  the control look like a no-op". Agreed, and it does not block this run.

## Verdict

**PASS.** The fix is correct, the test now exercises the artefact that ships
through the channel that ships it, and the mutation pair reddens on the old
script and passes on the new one for the right reasons. Safe to run per the
plan's own steps.

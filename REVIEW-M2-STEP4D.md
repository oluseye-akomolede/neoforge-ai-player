# Review — `01e9eaf` (bindings fallback fix) + `b1658af` (plan incident record)

**Row:** `qitem-20261111134152-3ded678504d2c55a`
**Verdict: PASS on both commits. One HOLD on the plan delta the lead asked me to
cover — the stale digest still sitting in §8.3.1.**

All measurements below were run by me in a clean `git archive` export of the
named rev. Where a number appears it is printed by the command beside it.

---

## 1. C1 closed — `01e9eaf` refuses the fallback, and the test guards both halves

The resolver no longer falls back to `dirname(__file__)/scripts`; with
`SCRIPTS_DIR` unset it prints why and returns `None`. The Dockerfile drops
`./scripts` from the runtime image.

**Mutant A (mine) — restore the fallback:**
```
FAIL: test_unset_scripts_dir_does_not_fall_back_to_the_image_copy
Ran 16 tests ... FAILED (failures=1)
```
Exactly the named test, nothing else. The guard is real.

**Mutant B (mine) — keep the refusal, drop the print:**
same test reddens, on the loudness assertion rather than the return value. So
the test covers both properties: it cannot pass while a baked-in map binds, and
it cannot pass while a refusal is silent. That is the two-guard shape, and I did
not have to ask for it.

**Suite at the rev**, eight modules, `agent/` as cwd:
```
Ran 92 tests in 1.264s
OK
```
92, not 82 — see §5.

## 2. C2 — the Dockerfile change removes nothing the agent needs

`agent/scripts/` contains exactly two files: `bindings.json` (26 bytes) and
`scout.js` (3526 bytes). Grepping every non-test module for a runtime reader of
that directory returns one hit, the resolver itself. `RUN rm -rf ./scripts` runs
at `WORKDIR /opt/aibot-agent`, after `COPY . .`, so it removes
`agent/scripts/` and matches nothing else in the build context.

The two-file removal is the whole change. Nothing else in the image is eaten by
the glob. **PASS.**

## 3. C3 — `b1658af` records the incident accurately

I verified the parts I can reach from this seat:

- **`server.js:151` is the `contract_version` refusal** — read it: the `409
  contract_version_unsupported` gate sits exactly there, before routing. The
  plan's citation resolves.
- **The record does not overclaim.** It says run 2's observations are
  diagnostics, names the two defects they found, and states that any §8.3.5 row
  reading a *difference* between the arms must be discarded rather than
  reconciled. That is the right instruction and it is stated once, where the
  rows are.
- **The typed-digest failure is recorded as a failure mode**, not just a
  corrected value — the next operator is told the first attempt left the pod
  `InvalidImageName` and that the value in the table is the registry's.

`openspec validate coded-agents --strict` at the rev, rev printed in the same
command:
```
REV: b1658af
Change 'coded-agents' is valid
```

**Not verified by me:** every cluster fact in §8.3.1a — the deploy, the
rollback, `1/1 Ready`, "five bots ticking", "zero `[Bot/script]` lines". No
cluster access from this seat. Taken as reported, and the record itself is
what I am reviewing, not the cluster.

## 4. HOLD — the plan delta carries a digest that is now stale

This is the lead's fourth item, and it is not yet satisfiable as written.

§8.3.1 row "Image (for this run)" still pins
`sha256:1b74ae7b…9506a4`, tag `2026-11-11-bf94724`. The very next row,
changed in `b1658af`, now says that image **must be rebuilt** after the
§8.3.1b fixes. The two rows contradict each other in the same table.

The mechanism for fixing it is correct and present: §8.3.2 step 0 says *"Pin the
pushed index digest into §8.3.1 before the rollout"*. But an operator reading
§8.3.1 — the cluster-facts table, which is where a deployer looks — sees a
digest with no "superseded" marker on it, and the digest is the one thing in
that table that must not be wrong.

**Fix:** mark the row's digest explicitly superseded until the rebuild lands
(the lead's own ordering — review, image, delta, review, OK — means the new
digest cannot be pinned yet), so the two rows cannot be read as agreeing.

This is a one-cell edit. It does not block the code.

## 5. Number correction — 92, not 82

`01e9eaf`'s message reports "77 passed + 5 subtests = 82 across the six
modules". The eight modules in `agent/` are **92** at this rev. Two of the six
in my earlier pass were names I had guessed (`test_script_bindings`,
`test_agent_script_routing`); the real set is
`test_action_binding`, `test_agent_script_branch`, `test_profiles_dir`,
`test_scout_script`, `test_script_client`, `test_script_tick`,
`test_scripts_configmap`, `test_snapshot`.

Not a defect in the code — the figure is a selection, and the commit message is
otherwise careful about which number it is. But 82, 92 and the earlier "55"
should not all circulate as "the suite". The reproducible number, from the eight
modules, is 92.

## 6. What the builder got right that I did not ask for

Mutant B — correct refusal, silent — was the half of C1 I framed as a
correctness question. They made loudness a tested property too. The docstring
reasoning ("quiet by design" is true for a bot absent from the map, false for
the map being absent) is the distinction I asked for, and they wrote it into the
code rather than the commit message.

---

## Summary

| item | verdict |
|---|---|
| C1 — fallback refused, mounts cannot silently bind | **PASS** — mutant A reddens the named test |
| C1 — refusal is loud | **PASS** — mutant B reddens it independently |
| C2 — Dockerfile removes nothing else | **PASS** — two files, one runtime reader, that reader is the fix |
| C3 — incident record accurate | **PASS** — `server.js:151` verified; no overclaim |
| Plan delta — new digest pinned | **HOLD** — §8.3.1 still shows the superseded digest |
| Suite tally | 92 at the rev, not 82 or 55 |

Nothing deployed. No build or push by me. No secret value printed.

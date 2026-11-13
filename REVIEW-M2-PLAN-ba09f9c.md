# Re-review — M2-PLAN §8.4, commit ba09f9c

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-13
Row: `qitem-20261113100843-1b24fe6e9c67c4c9`
Plan only. Nothing executed on the Deployment (read-only cluster reads).
Supersedes my review `ff3745a` (blocker on C2). See §"Withdrawn" below.

Verdict: **PASS WITH CORRECTIONS** — the blocker is genuinely resolved and the
run is sound. Three corrections, none of which change an arm's validity; one
(number) would fail a literal check if executed.

---

## WITHDRAWN — my blocker was wrong, and the builder's correction is right

On `ff3745a` I filed that a process-wide `SCRIPT_RUNNER_URL` cut would silence
all five bots, making §8.4.4 violate §8.3's "without cutting off every bot".
**That was wrong.** I verified the builder's claim independently at `ba09f9c`:

- `_get_script_tick` (`agent/agent.py:2804-2823`) returns `None` at `:2816`,
  **before** `script_tick` is imported (`:2818`) or `ScriptTick` constructed.
- Every production read of `SCRIPT_RUNNER_URL` is inside `script_tick.py`
  (`:194`, `:295`); `script_tick` has exactly one importer, the lazy
  `import script_tick` at `agent.py:2818`. An unbound bot never loads the module.
- Live confirm: the pod's log has **only** `[Scout/script]` lines; the other
  four bots emit none. Live `bindings.json` is exactly `{"Scout": "scout.js"}` —
  Scout is the only key, so requirement (a) is satisfied by the current state.

So the cut reaches bound bots only. §8.4.4's premise holds. The lead's option-2
ruling is sound, and the DELTA blocks at `:897` and `:926` honestly narrow §8.3
rather than deleting the constraint. I was wrong; recorded so my earlier
BLOCKER is not quoted as standing.

---

## CORRECTION 1 — the "134 lines in 20 minutes" figure is wrong, in count and window

§8.4.8 cites: *"the pod running the old image `a9e75ad1` … logged 134
`[Scout/script]` lines in 20 minutes"* as the measured basis for "the no-
regression check passes on the old image too". The conclusion is correct; the
number is not.

Measured now, same pod (`aibot-agent-test-6b65bdfc95-cbpz9`):
- `--since=20m` → **384** `[Scout/script]` lines, **195** `dispatch:` lines.
- `--since=10m` → the same 195, because the pod **started 10:38:02Z** and the
  log is only ~7.5 minutes long (first dispatch 10:38:25Z, last 10:46:00Z).
  A 20-minute window is longer than the pod has existed.

Two separate slips: the count (134 vs 195 dispatches / 384 lines) and the window
(20 min vs a pod 7.5 min old). Note also that `[Scout/script]` lines are emitted
in **pairs** per tick (`dispatch:` + `N action(s) this tick`), so a "line count"
and a "tick count" differ by ~2x and the plan does not say which it means.

**Why it matters:** this figure is the evidence that the acceptance check is a
no-regression check and not attributable to the fix. A reader (or a later run)
who executes "expect ~134 lines in 20 min" will see 195/384 and think something
regressed. **Fix:** state it as a rate with its window drawn from pod age, e.g.
"195 `dispatch:` lines in the pod's first ~7.5 minutes, ≈1 per 2.3s", and say
explicitly that `dispatch:` is the counted line, not the bare tag.

## CORRECTION 2 — the deploy-vs-RS diff hardcodes a ReplicaSet name that expires mid-run

§8.4.4 step 3 diffs the Deployment template against
`rs aibot-agent-test-6b65bdfc95` **by literal name**. That RS is the *current*
one. The moment step 3 resumes the Deployment with a patched env, a **new** RS
is created with a new hash; the restore creates another. Any later arm (C2b
inherits this, `:1922`) running this step against `6b65bdfc95` gets
`NotFound`.

I checked the failure mode rather than assuming: `kubectl get rs <missing>` fails,
its stdout is empty, and `sha256sum` over empty input is `e3b0c442…` — which does
**not** equal the Deployment side, so the step **stops**. Correct polarity (it
fails safe, no silent pass), but it will halt a run that should continue, and
the operator has to work out why.

The hash literal itself is fine: `fe1a4d3c…` is genuinely
`sha256(env array)` and both sides match today (I ran the exact two commands).
It is only the RS *name* that is stale-prone.

**Fix:** resolve the active RS instead of naming it, which I verified works:

```
kubectl -n minecraft-test get rs -l app=aibot-agent,tier=test \
  -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.readyReplicas}{"\n"}{end}' \
  | awk '$2==1{print $1}'
```

(returns `aibot-agent-test-6b65bdfc95` today). Require exactly one result, then
diff against that.

## CORRECTION 3 — precondition 1's `agent-scripts` hash names scout.js, not bindings.json

§8.4.3.1 says *"`agent-scripts` is `1824967e…` (scout.js) and `bindings.json` is
`{"Scout": "scout.js"}`"*. Both literals are **correct** — I verified
`1824967e…` is `sha256(scout.js)` and `10cef1b8…` is `sha256(bindings.json)` at
26 bytes. But the wording attaches the `1824967e…` hash only to scout.js and
gives `bindings.json` as a value rather than its hash. §8.4.6.1 *does* carry the
`10cef1b8…` / 26-byte figure, so the information exists — this is a readability
fix: put both hashes side by side in precondition 1 so a reader checking "is
the ConfigMap still the C4 state?" has both without cross-referencing.

---

## CONFIRMED (checked, not read)

- **C1 fixed correctly.** §8.4.6 uses absent-file, expects the `no bindings at …`
  line present **and** zero `dispatch:` lines, and carries the §8.3.4 `:1287-1290`
  warning against gating on the bare tag. This is exactly what I recommended; the
  old contradiction (configure one branch, expect the other's evidence) is gone.
- **Paused-deployment trap handled.** The Deployment is `paused: true` right now
  (`DeploymentPaused` condition), the active RS reconciles at 1, and
  delete-pod recreates from that RS. Step 3's sequence — **diff → patch →
  resume → recreate → prove env in the new pod** — closes the trap: the *resume*
  is what rolls the patched template into a new RS, so the recreate cannot pick
  up the stale one. My first read of this was wrong (I looked for a resume step
  in §8.4.2 and missed that step 3 supplies it).
- **Q1/Q2 dispositions correct.** C2a's void condition now keys on the detail
  prefix `connect refused:` rather than the state (right — `ConnectTimeout` also
  maps to `fallback_timeout`). §8.4.2's `bound_script_path()` warning is accurate
  and its §8.3.4 `:1179` exemption is right (used before the restart).
- **Q3/H1 honesty.** §8.4.8's "known limit" correctly scopes `aa7b00a` as
  undeployed and says a trap reason is suspect until it ships, while the controls
  remain valid because they cut the connection, not the sandbox. Agreed.
- **Lead's three points are in.** No-regression framing, cardgame session
  survival, flat restart/child-respawn count for 10 min, all present in §8.4.8.

## Bottom line

The plan is runnable once corrections 1–2 are applied (3 is cosmetic). Correction
1 should be fixed before anyone quotes the figure; correction 2 before C2b, or
C2b will halt on a `NotFound`. Neither requires another full review — send me the
two-line fixes and I will verify the literals and pass it. **I am not OK'ing the
run myself; that is the lead's call on row
`qitem-20261113100843-1b24fe6e9c67c4c9`.** Nothing was executed on the Deployment;
only read-only cluster reads were made.

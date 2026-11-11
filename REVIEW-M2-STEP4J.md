# Review — M2 step 4, ninth gate (`bf94724`) — **PASS**

**Row:** `qitem-20261111124635-9baa2a708ca95045`
**Verdict: PASS.** The plan is fit to execute and the code is fit to build as `85f6809`.

Reviewed in a clean `git archive bf94724` export.

- `openspec validate coded-agents --strict` → **"Change 'coded-agents' is valid", rc=0**, rev `bf94724` printed beside it.
- `85f6809..bf94724` touches **`M2-PLAN.md` only**. The code, the suite and both mutants I verified at `85f6809` still stand unchanged; nothing needs re-running.
- Suite in the export, eight modules including the ConfigMap drift test: **`Ran 84 tests, OK`**.

---

## 1. The fix — PASS

`c859de4..bf94724` is `+1/−1`: line 1229 now reads `at \`85f6809\`. Recompute it…`, the stale rev replaced **and** the run-on closed. Nothing else moved.

## 2. The provenance claim — conclusion right, detail imprecise

The builder swept six files across three revs and reported *"only `scout.js` changes hash across them, so `823920fd` has exactly one provenance."* I re-ran it:

| file | `d75f30b` | `85f6809` | `bf94724` |
|---|---|---|---|
| `agent/scripts/scout.js` | `7fdbad90` | `823920fd` | `823920fd` |
| `agent/script_tick.py` | `7eeaf3dd` | `7eeaf3dd` | `7eeaf3dd` |
| `agent/agent.py` | `805a7521` | `805a7521` | `805a7521` |
| `agent/snapshot.py` | `1f6e6361` | `1f6e6361` | `1f6e6361` |
| `agent/action_binding.py` | `728825f7` | `728825f7` | `728825f7` |
| `deploy/agent-scripts.yaml` | `447291f4` | **`23da7d28`** | `23da7d28` |

**Two files change, not one.** `deploy/agent-scripts.yaml` moves at the same rev because it embeds `scout.js`, and the diff is the health-guard change itself — the ConfigMap copy carrying the same edit, which the drift test enforces (`test_scripts_configmap.py:55`).

So the **conclusion is correct** — `823920fd` still has exactly one provenance, because the ConfigMap is a copy of the same script and not an independent source — but the stated fact is wrong. It matters only because the *method* was a uniqueness argument; a uniqueness check that miscounts the movers is not yet trustworthy. It did not cost anything here: the drift test is the real guard, and it passes.

## 3. Row 1's inline literal — my ruling: **leave it**

The builder asked whether row 1's bare `script_revision: 823920fd7277b98b` must carry its own rev inline, and flagged rather than widened the diff. That was the right instinct, and the answer is **leave it**:

- Row 1 is **governed** by the note at 1227-1231, which now names both the value and `85f6809` and instructs the operator to recompute against the shipping image. Same shape as row 2's `dispatch:` note — a row states the evidence, an adjacent note states its provenance and its failure mode.
- **Inlining the rev would rot.** The literal is recomputed per shipped image; the moment the rev sits in the row it becomes a second thing to keep in sync, and the value already changed twice in this run (`7fdbad90` → `823920fd`).
- The note explicitly says *"if the script changed, this value changes and a stale one in this table is the whole finding"* — it anticipates the rotation, which an inline citation would obscure.

**Rule for the next plan:** a row carries the observable; its provenance lives in a note that names the surface, unless the row is expected to survive several artifacts unchanged. Row 1 satisfies the first, does not satisfy the second.

## 4. What I verified across this exchange

| item | verdict |
|---|---|
| Route: `_run_script_tick` → `_l3_orchestrator_dispatch`, mixed/failed fall-through | **PASS** — 4 tests redden on the revert |
| `PROFILES_DIR` honoured, prod path unchanged when unset | **PASS** — 1 test reddens on hardcode |
| Task guard: envelope carries the running directive | **PASS** — mutants both ways, idle control |
| Health guard reads `state.health` | **PASS** — boundary sweep 8 / 7.9 / 0, both guards live |
| Fixtures built through the real producer | **PASS** — cache-level test green under the helper mutant, by design |
| Rows 1–6 name surfaces that emit their evidence | **PASS** — after four corrections this exchange |
| Revision `823920fd7277b98b` at the shipping rev | **PASS** — recomputed at `85f6809` and `bf94724` |
| `openspec validate --strict` at `bf94724` | **PASS** — valid, rc=0 |
| Map/fixture test under a blocked `yaml` | **PASS** — fails rather than skips |

## 5. Not verified by me — the run's own preconditions

Stated so the PASS is not read as wider than it is:

- **Every cluster fact.** Namespace, pod label, `PROFILES_DIR` on the live pod, the deployed image's provenance. No cluster access from this seat; the builder read some of these and I did not.
- **The initContainer manifest.** Written, not applied, not exercised. Its `cp -an` semantics are argued, not observed.
- **The runner end-to-end.** My `dispatch:`/`COMPLETED` and health-guard observations are from the agent suites and a node VM, which are the surfaces the rows name — not a live tick.
- **The image build.** Not built here. The deployer should re-run the digest check; nothing in this review substitutes for it.

**This PASS covers the plan and the code at `85f6809`. It does not pre-approve the run's outcome.**

Build and push may proceed. The digest goes to the lead, as the lead's item 3 requires.

Nothing built, nothing pushed, nothing deployed by me.

# Review — evals step 2.5 Job at `d78744f`

Reviewer: minecraft-reviewer@minecraft. 2026-11-13 ~17:05Z.
Scope: `evals/job-evals.yaml`, `evals/make-evals-configmap.sh`, plus the
`agent/output_evals` fixes in the same commit.

**Verdict: PASS with two findings and one conflict for the lead.**

Reviewed from `git archive d78744f` in a temp dir, not the working tree. The
tree was dirty throughout this review (`extract.py`, `test_extract.py`,
`test_run.py`) — the builder was rewriting the replay-pool tests while I read.
On the committed rev the suite is **66/66 OK**, so the builder's "66 tests OK"
is true of `d78744f`. I note below what happened when I ran the dirty tree,
because it is the exact instrument error I have made before.

---

## The three decisions, answered

### 1. Job declares no Secret but pulls a private image — HOLDS, and the reasoning is right

The builder asked whether this satisfies "no Secrets". It does, and the
mechanism is worth stating precisely because the question conflates two things:

- **Pulling** uses `imagePullSecrets` attached to the ServiceAccount, read by
  the **kubelet** from the SA object. That is why the manifest's comment at
  `:73` is correct: `ci`'s default SA carrying `harbor-creds` is enough, and the
  Job needs no Secret of its own.
- **`automountServiceAccountToken: false`** (`:39`) is about the **pod** getting
  an API token, which is a different thing entirely. Disabling it does not
  affect the pull.

So "no Secret in the Job, but the image still pulls" is coherent, not a
contradiction. The header comment at `:9-11` is accurate.

**What I could not verify:** whether `ci`'s default SA actually carries
`harbor-creds`. `kubectl` is not installed on this VM and the no-exec rule
stands, so this rests on the builder's statement. It is a one-line check on
controlplane (`kubectl -n ci get sa default -o jsonpath='{.imagePullSecrets}'`)
and **should be run before the first apply**, because the failure mode is a
`ImagePullBackOff` that looks like a registry problem, not a manifest problem.
The identical image works in the agent Deployment only because that manifest
declares `harbor-creds` explicitly (`deploy/agent-deployment.yaml:37-38`).

### 2. Endpoint in config.yaml not Job env — CORRECT, and the reason is the right one

The config is the artifact the report is signed against; an env override would
let the report name one endpoint while another served the calls. Writing it into
`config.yaml` and keeping `EVALS_ENDPOINT` only for interactive use, with
`endpoint_from_env` recorded in the report (`evalconfig.py:45,71,77,94`), is the
honest arrangement. A run scored against a non-default endpoint is a visible
diff to a tracked file rather than a hidden flag.

### 3. n=30 does not fit in 1 MiB — CONFLICT IS REAL, and the spec already contains the escape hatch

The generator refuses rather than silently truncating (`make-evals-configmap.sh:42-46`),
which is the right behaviour. But this is put to the lead as "the spec says 30,
the cap says 25" — and **the spec does not say a flat 30.** It says:

> `spec.md:120` — "The eval set MUST carry **at least about 30** cases for each of
> `plan`, `exec` and `replan`"

"at least **about** 30" is a deliberate hedge, and `n=25` sits inside it. The
builder wrote the conflict up as harder than it is. My recommendation to the
lead: **run at n=25 and state the number in the report**, rather than treating
this as a spec violation needing a spec change. 25 per kind is 75 cases, and the
requirement the owner cares about — enough cases to see a rate — is met.

I could not verify the 1,136,931 B figure: the corpus is on the PVC and not
reachable from here. It is plausible (≈12.6 KB/case implies long real prompts;
the extractor stores full prompts and does not truncate). It is the builder's
measurement and I am quoting it, not re-deriving it.

## Two findings

### A. (medium) The report's `short_of_30` is measured against the wrong pool

`extract.py:137` computes `max(0, MIN_PER_KIND - replay)` where `replay` is
`replayable` — the **all-era** replay pool. The spec's shortfall scenario
(`spec.md:157`) is about kinds short **in the current era**: "today: `replan`, 21".

Against the real corpus these differ sharply: `replan` has 271 replayable
(all-era) but only 21 current-era, so the report will print `short_of_30: 0`
while the spec's scenario wants `9`. The number the owner reads Friday would be
wrong in the direction that hides the shortfall — and the current-era shortfall is
exactly what the precedence paragraph (`spec.md:135-146`) is about.

The test `test_report_states_shortfall` asserts 9 and passes on its fixture only
because there all 21 calls are current-era, so the two measures coincide. The
test cannot distinguish them. **Fix:** compute the shortfall from the current-era
count, and add a case with an old-era minority where the two measures diverge.

### B. (low) `exit 3` prints "no labelled cases" for a condition that is no longer about labels

`run.py:226-227` returns 3 when `sum(n_cases) == 0`. Under the replay redesign a
call with no historical label **is** a case, so the gate is now "no cases", not
"no labelled cases". The message is stale and will mislead whoever reads the logs
when it fires — they will look for a label-join problem when the real cause is an
empty or unreplayable corpus. One-line message fix.

## What I verified and what I did not

**Verified on `d78744f` from a clean archive:** 66/66 pass; the 1 MiB guard and
its refusal path; the endpoint-in-config design and `endpoint_from_env` wiring;
the Job's SA/automount/Secret posture; config and code ship as two separate
ConfigMaps (`evals-scout-cases`, `evals-code`), so the per-ConfigMap size guard
is measuring the right object and the code tar staying out of the case-set number
is correct.

**Did not verify:** the corpus byte size (no PVC access); that `ci`'s default SA
carries `harbor-creds` (no kubectl here — **check before apply**); and the three
defect fixes' runtime behaviour beyond their unit tests, since the defects were
found by running against the corpus and I cannot reach it.

**A note on my own instrument.** I first ran the suite in the working tree and
got 5 failures, then 2, then a different set — because the builder was editing
`extract.py` and its tests while I ran them. Every one of those failures was in
their in-progress rewrite, not in `d78744f`. I nearly filed a "shipped with a
failing test" finding on the strength of it. Running the suite from
`git archive d78744f` gave 66/66 and dissolved it. The rule that saved me is the
one I have already recorded: review a sha, from an archive, never a working tree.

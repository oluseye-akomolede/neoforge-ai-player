# NOT PASS — 327e708 (manifests, base/minecraft/agent.yaml)

Reviewed from a bundle of `refs/heads/pin-agent-digest` into a scratch clone.
Single parent `e41368a`, one file, +40/-0. Live shapes read with read-only
`kubectl get` via `ssh controlplane`; no Secret values read.

## Verdict

NOT PASS. Not for the test half — that half is correct and should survive the
fix. The prod half adds to live instead of converging on it, and the commit
message asserts the opposite of the risk.

## Test half (aibot-agent-test): correct

Verified field by field against live `.spec.template.spec`:

| field | file at 327e708 | live |
|---|---|---|
| env NN_COMPRESSOR_URL | `http://nn-compressor.nn-compressor.svc.cluster.local` | same |
| env SCRIPT_RUNNER_URL | `http://agent-script-runner.minecraft-test.svc.cluster.local:8080` | same |
| env SCRIPTS_DIR | `/srv/aibot-scripts` | same |
| env RUNNER_TOKEN | secretKeyRef `agent-script-runner-token`/`minecraft` | same |
| mount scripts | `/srv/aibot-scripts`, readOnly | same |
| mount aibot-profiles | `/srv/aibot-profiles` | same |
| volume scripts | configMap `agent-scripts`, defaultMode 420 | same |
| volume aibot-profiles | emptyDir | same |
| initContainer seed-profiles | `agent:2026-11-05-c193f76`, IfNotPresent | same |

No deletions on test. This part discharges the deletion risk I raised on e41368a.

## Prod half (aibot-agent): the defect

`base/minecraft/agent.yaml:54-59` declares three literal env entries:

    - name: OMP_NUM_THREADS     value: "1"
    - name: MKL_NUM_THREADS     value: "1"
    - name: OPENBLAS_NUM_THREADS value: "1"

Live `minecraft/aibot-agent` has `spec.template.spec.containers[0].env` empty
(length 0). The thread vars reach the container through
`envFrom: secretRef agent-config` (`agent.yaml:47`), which is live and which the
file also declares.

327e708 does not remove them. So `kubectl apply` ADDS three env entries to live
prod that are not there now.

The commit message says: "live prod has no plain env and gets them from this
file, so the apply adds them rather than removing anything." That sentence is
offered as reassurance and is itself the finding. The lead's criterion (with my
refinement, agreed at 03:42Z) is that the file must equal live in BOTH
directions. Adding is a divergence exactly as removing is. A diff check tuned to
"no deletions" cannot see it, because these are `+` lines.

Consequence beyond the bytes: after the apply prod takes the thread vars from the
literal env and everything else from `agent-config`. If `agent-config` ever
changes them, the literal wins silently. The config source splits with no record.

## Fix

Remove `:54-59` (the three literal env entries) from the prod block only. The
test block's `:155-159` are correct — test's live env carries those three plus
the four new ones, and the file matches.

Alternatively, if the lead deliberately wants prod to carry them as literals and
drop them from `agent-config`, that is a spec decision and needs saying; it is
not a convergence commit.

## Self-correction, recorded

On e41368a I reported prod's live image as `agent:latest` with pullPolicy
Always, read from `kubectl.kubernetes.io/last-applied-configuration`. That is an
annotation recording a past apply, not the live spec. Both deployments' live
`.spec.template.spec.containers[0].image` are already
`agent@sha256:e80c2e8b…`; only the pull policy was drifting. The builder
corrected this and is right.

That error also invalidated my `containerPort` warning: I argued the file's port
must come out because last-applied lacked it. The port is live
(`5000/dashboard` on both deployments) and correctly stays. The general lesson is
already in my notes — reconcile against the bytes the consumer reads, not a
record of them — and last-applied is a record.

## Out of scope, carried so it is not lost

- `evals/job-evals.yaml` pins `a9e75ad1` and claims it is live; live is
  `e80c2e8b`. Builder flagged it; correct; needs its own row.
- `test-worlds/pod-template.yaml:139` still `:latest`/`Always`, no live pods.

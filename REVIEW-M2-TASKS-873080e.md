# Review — M2 task correction at `873080e`

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-11
Scope: `a80a323..873080e`, `tasks.md` only. Follows `REVIEW-M2-TASKS-73fd81f.md`.

## Verdict: PASS. The correction is right, and it is larger than the nit I raised.

## 1. What was actually wrong

I raised a nit: 4.2 said the runner had "its own k8s namespace" when the
manifest deploys into `minecraft-test`. The builder found that the same bullet
also said **"Remaining work is the deployment manifest and namespace"** — while
4.1 records that manifest as written and deployed. So one bullet both named a
namespace that does not exist and reported live work as remaining.

That second half is the more serious of the two, and it was in a `[x]` task
claiming DONE. A task can be ticked and still misdescribe its own scope.

## 2. The fix

    ~/minecraft/agent-script-runner` (no remote), deployed as the separate
    Deployment `agent-script-runner` **into the `minecraft-test` namespace**,
    shared with the game server rather than a namespace of its own (reviewer
    correction 11:25Z: an earlier wording said "its own k8s namespace" and
    pointed at one that does not exist) … The manifest is written and deployed
    (see 4.1); what remains is reachability fallback (4.3) and the M2 wiring.

Three properties worth naming:

- it states where the runner actually lands, not where it was imagined to;
- it records the correction and its date, so a reader who saw the old wording
  knows why it changed;
- "what remains" now points at 4.3 and the M2 wiring, both of which are still
  `[ ]`.

## 3. Verified

    grep "own k8s namespace|its own namespace|dedicated namespace"  ->  one hit,
        :265, the correction note quoting the old wording. No live claim survives.
    sed -n '259,269p'                                              -> reads as above.
    4.3 is `[ ]`. 8.2 is `[ ]`.
    openspec validate coded-agents --strict, at 873080e             -> valid, rc=0

## 4. One process note, not a defect

The handoff says "openspec validate --strict valid at **a80a323**". The commit
being handed over is `873080e`; validation was run on its parent. In this case
the amended rev is also valid — I ran it at `873080e` — so the conclusion holds.
But an amended rev is a new rev and needs its own check, and the message would
have read identically if the edit had broken validation. Worth running the
validator after committing, not before.

## 5. Cluster evidence

The builder checked the cluster rather than rewording from the document:
`kubectl -n minecraft-test get deploy agent-script-runner` → 1/1, and
`kubectl get ns | grep -i agent` → none. That is the right direction of
verification for a claim about where something is deployed, and it is the
correction being tested against the cluster rather than against my prose.

I cannot repeat that check — this seat has no `kubectl` or kubeconfig (stated
in `REVIEW-section5-2d88f1e.md` §6) — so the namespace absence is on their
report, backed by the manifest, which I have read.

## Standing

PASS, closed. `qitem-…102955` remains with the lead and is not this seat's to
close.

Co-Authored-By: Claude Code <noreply@anthropic.com>

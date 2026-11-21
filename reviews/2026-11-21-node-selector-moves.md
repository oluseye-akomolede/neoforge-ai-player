PASS on both moves, with one correction to the described effect on runner placement. Reviewed from the live cluster and the named revs; I did not apply anything.

VERIFIED
- Nodes: sigma-worker1, sigma-worker2, sigma-vm-worker1 all Ready, taints=none. control1 is the only tainted node. Both selector values are real hostnames.
- Live test-server: replicas=1, strategy=Recreate, nodeSelector=none, pod on sigma-worker2. Volumes are exactly minecraft-data-test-pvc and minecraft-mods-test-pvc, both longhorn RWX, no hostPath, hostNetwork, hostPID or affinity. The merge patch adds nodeSelector and nothing else; `nodeSelector: null` in a merge patch deletes the key. Rollback sound.
- Drift confirmed: file port 3100, live has 3100 modapi AND 3101 healthprobe. Not applying the file is right.
- Runner: live pod is on sigma-worker1 now; 074b442 adds only the 3-line nodeSelector; 9604fe4 changes only the digest to the live 600dc1c8. Manifest requests/limits match live (500m/4Gi, 2/12Gi). No GPU request. Apply and both rollbacks are sound.

CORRECTION (the one substantive point)
Moving the runner to vm-worker1 does NOT move the live pod. ReplicaSet 6856f79d94 carries no nodeSelector and has 1/1 ready, so the Deployment controller never scales it down; the new RS sits at 0 because the old one satisfies the replicas regardless of where its pod is. RollingUpdate does not reschedule a pod that is already Ready. So this change is dormant until the next runner image rollout or an explicit scale, and the validation that matters (the pod actually landing and staying on vm-worker1 under the 8/40Gi node) is not exercised by this apply.

That is fine as a placement rule to have on record, but do not report the move as done, and do not cite "kubectl diff now shows only the nodeSelector -> therefore moved" as the evidence. There is also a small change on the next rollout that is not in the description: the retirement is engine-image/longhorn-share-manager driven once the old pod goes (RollingUpdate maxSurge 25% rounds up to 1, so a validation pod can briefly share vm-worker1), so if vm-worker1 is memory-tight, expect a real eviction on that rollout rather than an idle move.

Check at that point: `kubectl -n minecraft-test get pod -o wide | grep agent-script-runner` shows sigma-vm-worker1, and `kubectl -n minecraft-test get rs` shows the old RS at 0.

Not blocking either apply.

# Review: e41368a — pin both agent deployments to the reviewed digest

Repo: `github.com/oluseye-akomolede/manifests`, branch `pin-agent-digest`, based on
`origin/main` `2e7c756`. Row: qitem-20261115033516-8d8247389179038b.
Reviewer: minecraft-reviewer@minecraft, 2026-11-15. Supersedes my review of
`91140f4` (committed at `942bc79` in the `minecraft-wt-qwen` worktree of
neoforge-ai-player).

## Verdict

**PASS on the change. Three things for the lead before applying, none of which
is a defect in this commit.**

## The change

Single parent (`git rev-list --parents -1 e41368a` names exactly `2e7c756`), one
commit ahead of `origin/main`, one file:

```
4 4  base/minecraft/agent.yaml
```

Four lines, both sites, exactly as requested:

```
-  image: harbor.arcadia-ecs.local/aiplayermod/agent:latest
-  imagePullPolicy: Always
+  image: harbor.arcadia-ecs.local/aiplayermod/agent@sha256:e80c2e8ba8d6aede7062f19eddc780b12277a601f2b91130e3ff7f4e74e2ad3a
+  imagePullPolicy: IfNotPresent
```

at `base/minecraft/agent.yaml:42-43` (`minecraft/aibot-agent`) and `:138-139`
(`minecraft-test/aibot-agent-test`).

**This is a different repo from where I found the defect, and that matters.**
`91140f4` changed `neoforge-ai-player/deploy/agent-deployment.yaml`, which is not
what the cluster is applied from: it names PVC `mindcraft-data`, has no `tier`
on any of the three label sites, no container port, and a kustomization pointing
at namespace `mindcraft`. The file reviewed here is the real one, and against it
the shape checks that failed for `91140f4` all hold:

| | this file | live `minecraft/aibot-agent` | live `minecraft-test/aibot-agent-test` |
|---|---|---|---|
| image | `@sha256:e80c2e8b…ad3a` | same | same |
| `claimName` | `agent-data` | `agent-data` | `agent-data` |
| namespace | `minecraft` / `minecraft-test` | matches | matches |
| `tier` on metadata/selector/template | prod / test | prod | test |
| container port | 5000 `dashboard` | same | same |
| `imagePullSecrets` | `harbor-creds` | same | same |

I confirmed the digest against the running pods, not just the Deployment spec:
`minecraft/aibot-agent-7cd57998cb-vcfkt` and the test pod both report
`imageID = …/agent@sha256:e80c2e8b…ad3a`. The pin target is the image that is
actually running, so applying this is a no-op for the running containers.

## For the lead before applying — three consequences of `IfNotPresent`

1. **`imagePullPolicy` on both deployments will change from `Always` to
   `IfNotPresent`.** That is the requested change, and it is correct for a digest
   reference: it stops every restart from re-verifying against the registry. It
   is still a live spec change, so "the pods are unchanged" will be true of the
   *image*, not of the pod template — a rollout will happen. Under
   `strategy: Recreate` on prod that is a stop-then-start of the agent that runs
   the 5 prod bots. Expect the bot to be briefly absent; that is not a failure.

2. **`harbor-creds` cannot pull this image from a cold node.** I checked the
   Secret's key without reading its value: `minecraft/harbor-creds` is
   `kubernetes.io/dockerconfigjson` with **1 key**, `.dockerconfigjson`, which
   can authenticate against exactly one registry. The image lives on
   `harbor.arcadia-ecs.local`; the digest was pulled before this pin, while the
   policy was `Always`, so the registry credential currently in use works. Under
   `IfNotPresent`, if a pod lands on a node that has never pulled this digest,
   the pull must succeed on its own — and if that node is cold for this image,
   there is no registry auth beyond this Secret. I could not verify the Secret
   covers `harbor.arcadia-ecs.local` without reading it, which I am not
   permitted to do. **Ask whoever owns it, or test on one pod first.** This is
   the one failure mode the pin can introduce that a server-side diff will not
   show you.

3. **A fourth site still says `agent:latest`.**
   `minecraft-manifests/test-worlds/pod-template.yaml:139` runs
   `harbor.arcadia-ecs.local/aiplayermod/agent:latest` with
   `imagePullPolicy: Always`, as the `agent` container of a per-world test Pod.
   Zero such pods exist right now (checked across all namespaces), so nothing is
   currently drifting on it. When it is used, it will pull whatever `:latest` is.
   Out of scope for this row; naming it so the next drift hunt starts here.

## Not a claim in this commit, and worth knowing

Neither manifest declares `OMP_NUM_THREADS` / `MKL_NUM_THREADS` /
`OPENBLAS_NUM_THREADS`, but both live Deployments **do** carry all three, set to
`"1"`, as the last live `kubectl edit`/patch left them. A literal
`kubectl apply -f base/minecraft/agent.yaml` will therefore remove three env
vars from the running pods. That is a real change to live behaviour (the
thread-throttling rule in the project brief), and it is invisible in `git diff`.
The lead plans a server-side diff before applying — this is the line it should
show. Three options: accept the removal, add the vars to the file so it
converges, or apply with `--prune`-free targeted patch. I am not filing this as
a defect because the file is not required to carry them and the owner of the
cluster decides; I am filing it because the apply will do it either way.

Related: `minecraft-test/aibot-agent-test` also carries `SCRIPT_RUNNER_URL`,
`SCRIPTS_DIR`, `RUNNER_TOKEN` (from secret `agent-script-runner-token`, key
`minecraft`), `NN_COMPRESSOR_URL`, plus volumes `scripts` (ConfigMap
`agent-scripts`) and `aibot-profiles` (emptyDir) and initContainer
`seed-profiles` (`agent:2026-11-05-c193f76`). A literal apply of this file
removes all of it. That is how test gets its script mode; losing it silently
turns script mode off. Same call to make, higher stakes than prod's env.

## Provenance caveats

- The branch `pin-agent-digest` is **not pushed** to GitHub
  (`git ls-remote --heads origin` lists six heads, none of them this one). I
  reviewed the commit object from the builder's local clone by bundling the ref
  into a scratch clone, and verified it is a single-parent child of
  `origin/main` `2e7c756` with the diff above. The lead's "apply from the
  reviewed sha" therefore needs the sha to exist somewhere durable before it is
  applied; an unpushed commit cannot be re-fetched later if the local clone is
  lost. Push it, or record the tree hash `3ed45cd` somewhere durable.
- I reviewed in a scratch clone (`mktemp -d`), not the builder's worktree.

## Partial retraction of my own F2

In my `91140f4` review I said prod's last-applied lacks env that the manifest
carries. That inverts here: the file carries env the live object lacks, and the
live object carries env the file lacks. Both statements were true of the
artefact I checked and I had the direction right in each; what I had wrong, in
the earlier review, was implying the neoforge-ai-player file was prod's manifest
at all. It is not, and the builder was right that it is stale and unapplied.

# Deployment Specification

## Purpose
Single source of truth for how the AI Player Mod, hive-mod, and agent are
built and shipped to the Kubernetes cluster. Replaces tribal knowledge so a
deploy is never blocked on "where does this jar go" or "which namespace."

There are two mods, both part of the frozen modpack and both shipped the same
way (to MinIO, pulled by the server's init container):

| Mod | Repo | JAR |
|-----|------|-----|
| AI Player Mod | `~/neoforge-ai-player` | `aiplayermod-1.0.0.jar` |
| Hive Mod | `~/hive-mod` | `hive_mod-0.1.0.jar` |

## Requirements

### Requirement: Environment Layout
Deployment MUST target exactly two namespaces: `minecraft` (prod) and
`minecraft-test` (test). The legacy `mindcraft` namespace is retired and MUST
NOT receive new work.

#### Scenario: Workloads per namespace
- GIVEN the cluster is queried for AI-bot workloads
- WHEN listing `minecraft-test`
- THEN it contains `minecraft-test-server`, `aibot-agent-test`, `pgvector`,
  `hive-service`, `l2-mcp`, `llm-gateway`, and the ollama deployments
- AND listing `minecraft` contains `minecraft-server`, `aibot-agent`, and
  `bot-registry`
- AND the test agent connects to `botmemory_test` while prod connects to
  `botmemory` on the same pgvector pod

### Requirement: Mod JAR Build
Both mod jars MUST be produced by Gradle in their own repo before upload.

#### Scenario: Build both mods
- GIVEN the mod source is checked out
- WHEN `./gradlew build` runs in `~/hive-mod` and `~/neoforge-ai-player`
- THEN `~/hive-mod/build/libs/hive_mod-0.1.0.jar` is produced
- AND `~/neoforge-ai-player/build/libs/aiplayermod-1.0.0.jar` is produced

### Requirement: Mod Deployment via MinIO
Mod jars MUST be uploaded to MinIO, not copied directly to the server. The
server's `mod-sync` init container clears `/mods` and re-pulls everything
from the bucket on every restart.

#### Scenario: Bucket layout
- GIVEN the `minecraft-mods` bucket
- THEN test jars live in `minecraft-mods/test/current/`
- AND prod jars live in `minecraft-mods/prod/current/`
- AND `tacz/` holds TACZ addons, `<env>/config/aiplayermod-shop.json` the shop
  config
- AND both `aiplayermod-1.0.0.jar` and `hive_mod-0.1.0.jar` MUST be present in
  the target `current/` directory

#### Scenario: Upload a mod to test
- GIVEN a freshly built jar
- WHEN deploying to test, the jar is copied with `mc`:
  ```
  mc cp ~/hive-mod/build/libs/hive_mod-0.1.0.jar \
        minio/minecraft-mods/test/current/hive_mod-0.1.0.jar
  mc cp ~/neoforge-ai-player/build/libs/aiplayermod-1.0.0.jar \
        minio/minecraft-mods/test/current/aiplayermod-1.0.0.jar
  ```
- THEN `mc ls minio/minecraft-mods/test/current/` shows both jars with fresh
  timestamps

#### Scenario: Promote test to prod
- GIVEN the test server has been validated with the new jars
- WHEN the operator runs the mod manager
  (`~/clustering/manifests/scripts/minecraft/mc-mods.sh promote`)
- THEN the current prod jars are archived to `prod/archive/<label>`
- AND `test/current/` is copied to `prod/current/`
- AND prod is NOT restarted automatically (operator runs `restart-prod` next)

### Requirement: Server Restart
A server MUST be restarted via `kubectl rollout restart`, never by deleting
the pod with `--grace-period`. The preStop hook saves the world via RCON and
the deployment uses `Recreate` strategy with a 300s grace period.

#### Scenario: Restart the test server
- GIVEN new mods are in `minecraft-mods/test/current/`
- WHEN `kubectl rollout restart deployment/minecraft-test-server -n minecraft-test`
  runs
- THEN the `mod-sync` init container re-pulls the mods from MinIO
- AND the server boots within the startup probe window (60 × 15s)
- AND the mod API answers `/health` on port 3100 when ready

### Requirement: Agent Deployment
Agent changes (Python, dashboard) MUST be shipped as a Docker image to Harbor,
not via MinIO. The agent image is `harbor.arcadia-ecs.local/aiplayermod/agent:latest`.

#### Scenario: Deploy the agent to test
- GIVEN a change to `~/neoforge-ai-player/agent/`
- WHEN the image is built and pushed:
  ```
  docker build -t harbor.arcadia-ecs.local/aiplayermod/agent:latest agent/
  docker push harbor.arcadia-ecs.local/aiplayermod/agent:latest
  kubectl rollout restart deployment/aibot-agent-test -n minecraft-test
  ```
- THEN the test dashboard reflects the new agent (`aibot-dashboard-test` on
  port 5000)
- AND the test agent uses `botmemory_test`, the llm-gateway for chat, and
  `USE_L3_PLAN_LAYER=true`

### Requirement: Prod Agent Promotion (pending)

The prod `aibot-agent` (namespace `minecraft`) is intentionally NOT redeployed
during the v10–v12 skill/RL development push. Two prod changes are already
committed to `base/minecraft/agent.yaml` but NOT applied to the prod cluster;
apply them together at promotion time:

- `OLLAMA_URL` (prod `agent-config` secret) repointed from the retired
  `ollama.mindcraft` to `ollama-l3.minecraft-test.svc.cluster.local:11434`
  (v12). Prod still resolves the dead service until this is applied.
- `USE_L3_PLAN_LAYER` is still unset on prod (legacy decompose path). Set it
  to `"true"` once the skill-aware plan layer is validated in test — that is
  the actual "skills first, directives fallback" switch for prod (v10/v12).

Prod and test share the `harbor.arcadia-ecs.local/aiplayermod/agent:latest`
image with `imagePullPolicy: Always`, so a prod pod restart already pulls the
v12 agent (behavioral replay-memory retired, `plan_memory` replay skill-only).
Safe for prod — it runs the legacy path, which never reaches `plan_memory` —
but treat any prod restart as a mini-promotion and verify it.

### Requirement: Manifests Are The Source of Truth
Cluster manifests MUST live in `~/clustering/manifests` (GitHub:
`oluseye-akomolede/manifests`) and be committed after any live change, so the
repo never drifts from the cluster.

#### Scenario: Reconcile drift
- GIVEN a change was applied directly with `kubectl` during debugging
- WHEN the change is confirmed working
- THEN the corresponding manifest in `base/minecraft/` is updated
- AND committed and pushed to the `helm-kustomize-restructure` branch
- AND a future `kubectl apply -k base/minecraft` reproduces the live state

### Requirement: Verification
A deploy MUST be verified by observing a healthy server and agent, not merely
by a successful upload.

#### Scenario: Confirm test deployment
- GIVEN a restart completes
- WHEN the operator checks status
- THEN `kubectl get deploy -n minecraft-test` shows `1/1` ready for both
  `minecraft-test-server` and `aibot-agent-test`
- AND `kubectl logs deployment/minecraft-test-server -n minecraft-test -c mod-sync`
  reports the expected jar count
- AND the test dashboard is reachable at
  `http://aibot-dashboard-test.taildfdd3b.ts.net:5000`

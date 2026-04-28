# Test Environment Specification

## Purpose
Defines the automated bot testing infrastructure — lightweight NeoForge Minecraft worlds orchestrated via Kubernetes for running bot behavior tests against serialized bot images.

## Requirements

### Requirement: NeoForge Test Worlds
Test worlds MUST run lightweight NeoForge 1.21.1 servers with only the AI Player Mod installed. No additional modpacks or world generation mods are loaded.

#### Scenario: Minimal server boot
- GIVEN a test world pod is created
- WHEN the NeoForge server starts
- THEN only the aiplayermod JAR is loaded
- AND the server is ready to accept bot spawns within 90 seconds
- AND the world uses a flat or void superflat preset for fast generation

### Requirement: Pod-Per-World Architecture
Each test world MUST run as an isolated Kubernetes pod containing a NeoForge server container and a sidecar agent container.

#### Scenario: Test world pod composition
- GIVEN a test run requests a new world
- WHEN the pod is created
- THEN it contains two containers:
  - `mc-server`: NeoForge 1.21.1 with aiplayermod, ports 25565 + 3100
  - `agent`: Python agent with dashboard, port 5000
- AND the pod has resource limits (CPU: 1 core, memory: 2Gi for server; 500m, 512Mi for agent)
- AND the pod has a TTL or cleanup policy to prevent orphaned worlds

### Requirement: Shared Ollama
All test world agents MUST connect to the shared Ollama instance for LLM inference rather than running their own. The Ollama URL is injected via environment variable.

#### Scenario: Agent uses shared Ollama
- GIVEN the cluster has an Ollama deployment at ollama.mindcraft.svc.cluster.local:11434
- WHEN a test agent starts
- THEN it connects to the shared Ollama for L3 planning
- AND the global ollama_lock serialization still applies (one request at a time per agent)

### Requirement: Shared PostgreSQL
Test agents MUST connect to the shared pgvector PostgreSQL instance for semantic memory, task board, and registries.

#### Scenario: Test agent connects to shared database
- GIVEN pgvector is deployed at pgvector.minecraft-test.svc.cluster.local:5432
- WHEN a test agent initializes
- THEN it creates its own tables (namespaced by bot names) in the shared database
- AND test data does not collide with production data

### Requirement: Bot Image Deployment
The test harness MUST pull bot images from the bot-registry and restore them into the test world using botshare CLI tooling.

#### Scenario: Deploy a bot image to a test world
- GIVEN a bot image "axiom:v1" exists in the registry
- AND a test world pod is running
- WHEN the test harness initiates deployment
- THEN the image is pulled from the registry via botshare CLI or registry API
- AND the bot is spawned in the test world
- AND all layers (profile, memory, inventory, xp, brain, transmute, identity) are restored

### Requirement: Test Harness
The system MUST provide a test harness that orchestrates test runs: create world, deploy bots, execute test scenarios, collect results, tear down.

#### Scenario: Run a behavior test
- GIVEN a test definition specifying:
  - Bot image: axiom:v1
  - World type: flat
  - Scenario: "mine 10 minecraft:iron_ore"
  - Success criteria: inventory contains >= 10 raw_iron within 120 seconds
- WHEN the test harness executes the test
- THEN a test world pod is created
- AND the bot image is deployed
- AND the scenario instruction is sent via inject_chat
- AND the harness polls bot status until success criteria met or timeout
- AND results (pass/fail, duration, logs) are collected
- AND the pod is torn down

### Requirement: Test Definition Format
Test scenarios MUST be defined in a declarative format (YAML or JSON) specifying bot images, world configuration, instructions, and success criteria.

#### Scenario: YAML test definition
- GIVEN a test file `tests/mine_iron.yaml`:
  ```yaml
  name: mine-iron-basic
  world:
    type: flat
    seed: 12345
  bots:
    - image: axiom:v1
      restore_layers: [profile, memory]
  steps:
    - instruction: "Mine 10 minecraft:iron_ore"
      timeout: 120
      success:
        inventory_contains:
          item: minecraft:raw_iron
          min_count: 10
  ```
- WHEN the test harness processes this file
- THEN it creates a world, deploys the bot, and validates the criteria

### Requirement: Test Result Reporting
Test results MUST be collected and reported with pass/fail status, execution duration, bot logs, and failure details.

#### Scenario: Test failure report
- GIVEN a test expects 10 iron ore but the bot only mined 3 before timeout
- WHEN the test harness reports results
- THEN the report includes:
  - Status: FAIL
  - Expected: >= 10 minecraft:raw_iron
  - Actual: 3 minecraft:raw_iron
  - Duration: 120s (timeout)
  - Bot logs: last 50 agent events

### Requirement: Parallel Test Execution
Multiple test worlds MUST be able to run simultaneously, limited only by cluster resources.

#### Scenario: Run 5 tests in parallel
- GIVEN 5 test definitions
- WHEN the test harness launches all 5
- THEN 5 separate pods are created
- AND each runs independently with its own world and bots
- AND results are aggregated when all complete

### Requirement: World Cleanup
Test world pods MUST be cleaned up after test completion (pass or fail). A TTL-based fallback MUST prevent orphaned pods from consuming resources.

#### Scenario: Cleanup after test
- GIVEN a test world pod has been running for 10 minutes
- AND the test has completed
- WHEN cleanup runs
- THEN the pod and its volumes are deleted
- AND any bot data in the shared database is optionally preserved for debugging

#### Scenario: Orphan cleanup
- GIVEN a test world pod has exceeded its TTL (default: 30 minutes)
- WHEN the TTL controller checks
- THEN the pod is forcefully deleted regardless of test status

### Requirement: Namespace Isolation
All test workloads MUST run in a dedicated Kubernetes namespace (e.g., `minecraft-test`) separate from production.

#### Scenario: Test pods in dedicated namespace
- GIVEN the test namespace is `minecraft-test`
- WHEN a test world pod is created
- THEN it is created in the `minecraft-test` namespace
- AND it has no network access to production minecraft pods

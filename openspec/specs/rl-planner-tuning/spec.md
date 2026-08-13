# RL Planner Tuning Specification

## Purpose

Defines the offline RL pipeline that fine-tunes the L3 planner
(`qwen2.5:14b-instruct`) to produce better plans, using the deterministic
`criteria_eval` outcome as reward.

## Requirements

### Requirement: Trajectory capture
Every L3 call MUST be logged as a `(prompt, raw response, parsed output,
world-state summary, outcome)` record in an append-only JSONL trajectory
log. The `outcome` MUST be the deterministic `criteria_eval` result, backfilled
after the subtask settles, never L3's self-report.

#### Scenario: A call is logged with a deterministic outcome
- GIVEN a bot executes a subtask whose criterion passes under `criteria_eval`
- WHEN the plan closes
- THEN the trajectory record for that exec call carries `outcome` reflecting
  the pass
- AND the raw L3 response is present verbatim (not just the parsed plan)

### Requirement: Deterministic reward, no learned reward model
The reward MUST be computed by the existing `criteria_eval` strategies, plus
a schema-validity term and a cost term. No separate reward model is used.

#### Scenario: Reward reflects verifiable success
- GIVEN an exec response whose directives, when run, satisfy the subtask
  criterion under a deterministic strategy
- THEN the reward is 1.0 minus the cost term
- AND a response that is not valid plan JSON is rewarded -1.0

### Requirement: Cost penalty
The reward MUST include a penalty proportional to plan cost (number of
directives / output tokens), so the model is discouraged from over-decomposing
at the expense of the shared local GPU.

#### Scenario: Verbose plan is penalized
- GIVEN two responses that both satisfy the criterion
- WHEN one emits 8 directives and the other emits 2
- THEN the 2-directive response receives the higher reward

### Requirement: Criteria laundering guard
The reward and evaluation MUST use the same criterion the plan carried, and a
fine-tuned model that emits weakened criteria MUST be rejected regardless of
its success rate.

#### Scenario: Weakened criteria rejected
- GIVEN a fine-tuned model emits a replan that rewords "killed 200 enemies"
  into a non-verifiable synonym
- WHEN the drift guard runs
- THEN the checkpoint is rejected

### Requirement: DPO then GRPO
The pipeline MUST support an offline DPO stage (preference pairs from the
archive) followed by an online GRPO stage (sampled plans executed and
rewarded deterministically).

#### Scenario: GRPO reward uses the verifier
- GIVEN K sampled plans for a task
- WHEN each is executed (or replay-verified) against the deterministic reward
- THEN group-relative advantage is computed over those K rewards
- AND the policy updates from that advantage

### Requirement: Local-only training
Training MUST run on local GPUs against the locally-served model weights; no
training or inference leaves the cluster. L2 MUST remain zero-decision and the
mod MUST be untouched by the pipeline (trajectory capture is agent-side).

#### Scenario: No L2 or mod change
- GIVEN the RL pipeline is active
- WHEN a trajectory is logged and a reward computed
- THEN both happen in the agent process
- AND no mod code or L2 decision path is altered

### Requirement: Reversible rollout
The fine-tuned model MUST be exported under a new ollama tag alongside the
original, and MUST be canaried on a single bot before fleet-wide adoption,
with the original tag retained for instant rollback.

#### Scenario: Canary before fleet
- GIVEN a fine-tuned checkpoint passes the holdout suite
- WHEN it is served as a new tag
- THEN one bot is switched to it first
- AND the fleet is switched only after the canary shows no regression

# Agent output evals — measure whether the local model's decisions are correct

## Why

The owner (11-12 06:57Z, `qitem-slack-inbound-1d08882b6d9f54767672`): "all agent
output needs evals to ensure they are working properly. This is especially
important for Minecraft since it is primarily making use of the local model."

Every bot decision that shapes play comes out of one local model —
`qwen3-coder:30b` served through Ollama at `OLLAMA_URL`. Today there is no
number saying how often that model's output is usable. Regressions are found by
watching a bot do something silly, and a change to the prompt, the model tag or
the serving stack has no before/after comparison to be judged against. The LoRA
write-up (11-15) needs a baseline for exactly this reason: without one, "the
fine-tune helped" is an impression.

This change is **step 1: the spec**. It inventories every place the agent asks
the local model for something, defines what "correct" means for each kind of
output, and specifies a repeatable eval set, scorer, runner config and report.
No code in this step.

## What Changes

- **NEW `agent-output-evals`** — a capability beside the agent, not inside it.
  The agent's prompts and call sites are consumed as they stand; the eval
  harness reproduces the same requests against a recorded input and scores the
  shape and validity of the answer.
- **Existing behaviour: unchanged.** No live requirement is modified. The
  harness MUST NOT require the production agent to log differently or call
  differently. Where the eval needs recorded input and the agent does not
  currently record it, this change says so explicitly rather than pulling a new
  logging requirement into the agent.

## What is already recorded, and what is not

This determines how the eval set can be sourced, so it is part of the design,
not an implementation detail.

- **Plan / exec / replan: recorded, but the ground truth is joined for `exec`
  only.** `agent/trajectory_log.py` writes an append-only JSONL stream
  (`agent_trajectories/trajectory-YYYY-MM-DD.jsonl`) with, per call,
  `prompt_system`, `prompt_user`, `world_state_summary`, `response_raw`,
  `parsed`, `parse_error` and `plan_ref`. An `outcome` record (`satisfied`,
  `strategy`, `reason`) is written on `call_id` — but `log_outcome` is called
  once in the repo (`plan_orchestrator.py:616`) and only for `exec`; neither
  `call_plan` nor `call_replan` returns the `call_id` its record was written
  under. `plan` and `replan` therefore get their labels through `plan_ref` and
  the plan archive, which is a derivation the report must name.
- **Chat, classify, fleet-partition, regenerate: not recorded.** These paths
  call `OLLAMA_URL` and log nothing. Their eval inputs must be sourced another
  way, and the proposal says which; see the inventory.
- **Skill author and L5: an online model, not the local one.** `skill_author.py`
  and `l5.py` both call `{DEEPSEEK_URL}/chat/completions` with
  `DEEPSEEK_MODEL` (default `deepseek-v4-flash`). The name `_deepseek_chat` reads
  like a local helper and is not one. They are out of scope for the local-model
  baseline; if they are ever in scope they are a separate eval against a
  different endpoint.

## The corpus has no durability guarantee

The corpus the eval is built from is written wherever `agent_trajectories/`
falls under the agent's working directory, and **nothing persists it**. The only
PVC in `deploy/agent-deployment.yaml` mounts at `/opt/aibot-agent/data`;
`trajectory_log.DIR` resolves to `dirname(PROFILE_PATH)/agent_trajectories` —
`/opt/aibot-agent/profiles/agent_trajectories` when `PROFILE_PATH` is set as
`deploy/agent.env.example` shows, or `/opt/aibot-agent/agent_trajectories` if it
is not — and no manifest sets `AIBOT_TRAJECTORY_DIR`. Either way it is
container-local: a restart destroys it, including this morning's 14:53Z
rollout.

So the sizing in this change is a target, not a measurement. **Step 2 counts
what exists before any kind is promised 30 cases**, and reports a shortfall as a
shortfall. Making the corpus durable (a `subPath` on the existing PVC, or an
`AIBOT_TRAJECTORY_DIR` under `/opt/aibot-agent/data`) is a separate, small
change this one depends on — it is not built here.

## Owner decisions

1. **Automatic checks first.** Prefer schema/parse validity, action-in-allowed-
   surface with valid parameters, plan achievable from the given state, and the
   expected outcome reached. A judge model only where nothing else works, and
   it must be named in the report.
2. **Rerun by config only.** The same eval set must run against a different
   model or endpoint by changing a config file — this is the yardstick the LoRA
   write-up uses.
3. **30 cases per output kind** for the main planner, minimum.

## Non-goals

- Scoring the *in-game* outcome of a real bot. That stays `criteria_eval`'s job
  in production; the eval uses its verdict as a label, it does not replace it.
- Changing the model, the prompts, or the serving stack.
- A dashboard UI for eval results. The report is a file.

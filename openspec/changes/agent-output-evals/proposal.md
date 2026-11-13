# Agent output evals — measure whether the local model's decisions are correct

## Why

The owner (11-12 06:57Z, `qitem-slack-inbound-1d08882b6d9f54767672`): "all agent
output needs evals to ensure they are working properly. This is especially
important for Minecraft since it is primarily making use of the local model."

Every bot decision that shapes play comes out of one local model served through
Ollama at `OLLAMA_URL`. Its tag is not a constant: it comes from each bot's
profile (`agent/agent.py:183`), and the live one is `qwen3-coder:30b`. Today
there is no number saying how often that model's output is usable. Regressions
are found by watching a bot do something silly, and a change to the prompt, the
model tag or the serving stack has no before/after comparison to be judged
against. The LoRA write-up (11-15) needs a baseline for exactly this reason:
without one, "the fine-tune helped" is an impression.

This change is **step 1: the spec**. It inventories every place the agent asks
the local model for something, defines what "correct" means for each kind of
output, and specifies a repeatable eval set, scorer, runner config and report.
No code in this step.

## The eval is a replay eval

The primary measurement is a **replay**: take a recorded input
(`prompt_system` + `prompt_user` from the trajectory log), re-send it to the
configured model, and score the *new* output with automatic checks. It answers
"is the model I am running today producing usable output?" — which is the
question a LoRA yardstick needs, because the same fixed inputs run against the
old and the new model.

Because the automatic checks judge the output's own shape and validity, they
need no outcome join. All three main-planner kinds are therefore testable from
the recorded inputs alone.

A **historical, outcome-attributed score** is reported separately: what the
recorded responses actually achieved in play. It is secondary, and it is not
equally strong across kinds — see below.

## What is already recorded, and what is not

This determines how the eval set can be sourced, so it is part of the design,
not an implementation detail.

- **Replay inputs: recorded for `plan`, `exec` and `replan`.** `agent/trajectory_log.py`
  writes an append-only JSONL stream (`$AIBOT_TRAJECTORY_DIR`, default
  `agent_trajectories/trajectory-YYYY-MM-DD.jsonl`) with, per call,
  `prompt_system`, `prompt_user`, `world_state_summary`, `response_raw`,
  `parsed`, `parse_error`, `bot`, `model` and `plan_ref`. The corpus is on the
  agent's PVC and survives restarts; the directory is read from config/env
  (`AIBOT_TRAJECTORY_DIR`), never hardcoded.
- **Outcome attribution: `exec` only.** An `outcome` record (`satisfied`,
  `strategy`, `reason`) is written on `call_id` — but `log_outcome` is called
  once in the repo (`plan_orchestrator.py:616`) and only for `exec`; neither
  `call_plan` nor `call_replan` returns the `call_id` its record was written
  under. `plan` and `replan` get a plan-level label through `plan_ref` → the
  terminal `plan_close` record's `status`, which is weaker: a plan that closed
  `complete` does not mean every subtask it proposed was good.
- **Chat, classify, fleet-partition, regenerate: not recorded.** These paths
  call `OLLAMA_URL` and log nothing. Their eval inputs must be sourced another
  way, and the inventory says which.
- **Skill author and L5: an online model, not the local one.** `skill_author.py`
  and `l5.py` both call `{DEEPSEEK_URL}/chat/completions` with
  `DEEPSEEK_MODEL` (default `deepseek-v4-flash`). The name `_deepseek_chat` reads
  like a local helper and is not one.
- **The local endpoint also serves an embedding model**, `nomic-embed-text`,
  which is not the model any bot plans or speaks with. It is named and scoped
  out in the inventory.

## Owner decisions

1. **Automatic checks first.** Prefer schema/parse validity, action-in-allowed-
   surface with valid parameters, plan achievable from the given state, and the
   expected outcome reached. A judge model only where nothing else works, and
   it must be named in the report.
2. **Rerun by config only.** The same eval set must run against a different
   model or endpoint by changing a config file — this is the yardstick the LoRA
   write-up uses.
3. **30 cases per output kind** for the main planner, minimum, sampled
   stratified from what the corpus holds — and the count of what the corpus
   holds is reported first.

## Non-goals

- Scoring the *in-game* outcome of a real bot. That stays `criteria_eval`'s job
  in production; the eval uses its verdict as one label among several, it does
  not replace it.
- Changing the model, the prompts, or the serving stack.
- A dashboard UI for eval results. The report is a file.
- Fixing the agent's own directive-kind gap (`_VALID_DIRECTIVE_KINDS` is missing
  `AREA_LOOT` and `SKILL`). It is a live agent bug, filed separately.

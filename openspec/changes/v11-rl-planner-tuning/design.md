# v11 design — RL fine-tuning of the L3 planner

## Context

- **Target model**: `qwen2.5:14b-instruct` (L3), served by `ollama-l3` on the
  V100 pair, fronted by `llm-gateway`. The planner is `agent/l3_planner.py`:
  `call_plan` (Phase 1, lines 137–176), `call_exec` (Phase 2, lines 430–468),
  `call_replan` (lines 497–539). Prompts at `_PLAN_SYSTEM_PROMPT` (62–134),
  `_EXEC_SYSTEM_PROMPT` (182–352), `_REPLAN_SYSTEM_PROMPT` (474–494).
- **Plan/state**: `agent/plan_schema.py` (`Subtask`, `Plan`); files at
  `agent_plans/{bot}_current.json` + `archive/` via `agent/plan_store.py`.
- **Deterministic outcome**: `agent/criteria_eval.py` — the four-strategy
  evaluator (world-state query → kill-stat delta → L1 result → L3 fallback).
  This is the reward oracle.
- **Verifier environment**: ephemeral NeoForge test worlds under
  `agent/testing/` (minecraft-test ns); the R5 harness hit 37/40.
- **Hardware**: L3 inference = V100 16GB×2 (fp16). Training candidates =
  A4000 16GB×2 on worker2 (bf16, Ampere) primary; V100 pair (fp16) fallback.

## Goals / Non-Goals

**Goals:** a reproducible offline RL pipeline that improves plan success rate
on a holdout suite; deterministic reward; local-only; reversible rollout.

**Non-Goals:** learned reward model; cloud; touching L2 decision-making; a
general-purpose model.

## Decisions

### 1. Target the per-bot planner first; hive-service second

Train `neoforge-ai-player/agent/l3_planner.py` (the live fleet path). The
hive-service Lieutenant/Coordinator planner (`hive-service/app/l3_planner.py`)
is the older path and is out of scope until the fleet planner shows a gain.

### 2. Reward is the existing criteria evaluator, plus a format term and a cost term

No learned reward model. For a subtask-execution turn:

```
R = criteria_met(criteria_eval(subtask, world_state)) ? 1.0 : 0.0
  + (schema_valid(response) ? 0.0 : -1.0)      // must keep emitting valid JSON
  - λ · cost(response)                          // # directives / output tokens
```

For a plan turn, `R = mean(subtask R)` (or `1.0 if all met else 0.0`).
`λ` is tuned so cost discourages over-decomposition without starving correct
plans — the 14B at 60 tok/s is the fleet's shared bottleneck.

- **Why deterministic verifier, not a model**: the war-test lesson — L3 tried
  to launder "killed 200 enemies" into "eliminations" and was blocked by
  carrying criteria verbatim. The reward MUST come from the same
  `criteria_eval` (world-state/kill-stat/L1), never from L3's self-report, or
  the model learns to game wording instead of accomplish tasks.
- **Why a format term**: structured output is load-bearing; a model that
  drifts out of JSON-schema compliance must be penalized hard.

### 3. DPO first, GRPO second

- **R3 DPO**: from the archive, pair (successful exec's directives,
  failed exec's directives) for the same or similar subtask prompt → chosen /
  rejected. `DPOTrainer` + QLoRA. Off-policy, cheap, no live execution; it
  captures "what historically worked" and gives an immediate, low-risk win.
- **R4 GRPO**: sample K completions per task prompt from the current policy,
  execute each in a headless world, reward via Decision 2, optimize with
  group-relative advantage (`GRPOTrainer`). On-policy exploration is the only
  thing that improves *beyond* recorded data. Depends on the headless
  verifier and benefits from v10's smaller decision space.
- **Why both**: DPO bootstraps the policy toward known-good shapes cheaply;
  GRPO then explores. DPO alone can't generalize to novel open-ended tasks
  ("search, loot, store") that never appear verbatim in the archive.

### 4. Verifier: offline replay for the inner loop, live headless for validation

- **Offline replay** (fast, approximate): evaluate a sampled plan against
  recorded world-state snapshots captured at task receipt, using the same
  deterministic checks. Used for the GRPO inner loop where we need thousands
  of reward evaluations.
- **Live headless** (slow, exact): run the plan in a fresh ephemeral
  NeoForge world (`agent/testing/`) and evaluate criteria for real. Used for a
  smaller validation set and for R5.

### 5. Framework and quantization

- **Stack**: `TRL` (`SFTTrainer`/`DPOTrainer`/`GRPOTrainer`) + `unsloth` (for
  speed) + `bitsandbytes` (NF4). Single-node, no Ray.
- **QLoRA 4-bit** NF4 base + LoRA (rank 16–64) + paged AdamW. 14B 4-bit ≈
  8 GB of weights; adapters + activations + optimizer fit in 32 GB.
- **Precision**: A4000 (Ampere) → bf16 preferred. V100 (Volta) → fp16 only
  (no bf16 tensor cores); both are supported by bitsandbytes/unsloth. Prefer
  A4000×2 for training so the V100 pair keeps serving inference uninterrupted.
- **Export**: merge LoRA → full precision → GGUF (Q4_K_M) → `ollama create`
  under a new tag; `llm-gateway` serves the tag. Original model kept
  side-by-side for instant rollback.

### 6. Evaluation and rollout

- **Holdout suite**: the endurance tasks (`deep-mine-expedition`,
  `night-watch`, `operation-basecamp`) + war-test kill criteria. Success rate
  must not regress vs. baseline, and must improve on the known-variance
  failure cases.
- **Canary**: serve the fine-tuned model as a second ollama tag; point ONE
  bot's `OLLAMA_URL`/model at it (per-client override through the gateway or
  a per-bot config) before fleet-wide switch.
- **Reward drift guard**: re-run the "criteria not laundered" war-test case
  against the fine-tuned model; if it emits weakened criteria, the checkpoint
  is rejected regardless of headline success rate.

## Constraints honored

- **Local-only**: qwen2.5:14b weights are already local (ollama). Downloading
  open base weights to fine-tune is not a "cloud LLM service" — it's the same
  model already running; no inference leaves the cluster.
- **Frozen modpack**: R1 is an agent-side logger; nothing touches the mod.
- **L2 untouched**: RL changes L3 weights only; the zero-decision L2 boundary
  is preserved.

## Risks / Trade-offs

- **GRPO on 14B is slow** → QLoRA + unsloth + a bounded task set keep it a
  days-scale job, not weeks. Start with DPO (hours) and gate GRPO behind a
  demonstrated DPO gain.
- **Reward hacking** → the deterministic verifier + format term + the
  criteria-verbatim guard are the mitigations; the drift guard (Decision 6)
  is the tripwire.
- **Distribution shift** → fine-tuned plans reference skills (v10) and live
  world state; keep world-state summaries in the training prompt identical in
  shape to production so the policy doesn't overfit the verifier's world.
- **Hardware contention** → training must not evict the L3 inference model
  from the V100 pair; that is why A4000×2 is the primary training target.

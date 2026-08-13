# v11 — RL fine-tuning of the L3 planner

## Why

The endurance ladder plateaued at 37/40 for a reason we've now characterized
precisely: the remaining failures are **LLM output variance, not code bugs**
— wrong counts, unnecessary steps, timing. Prompt tuning has hit diminishing
returns, and the standing rule is to stop chasing it. Two structural levers
are left:

1. **v10 — move correctness out of the LLM** (deterministic skills).
2. **This change — change the LLM's weights** so the plans it does emit are
   better, using the verifier we already have.

The key discovery that makes this tractable (rather than a research project):
**the reward function and the trajectory data already exist.** The agent's
`criteria_eval` already computes deterministic per-subtask pass/fail against
world state, kill-stat deltas, and L1 results; and `agent_plans/{bot}_*.json`
already logs every plan's subtasks, directives, and outcome. What is missing
is only the *raw* `(prompt → L3 response → outcome)` triple — today the
archive stores the parsed plan, not the exact prompt and raw model output.

This is the same shape CrossAgent used (SFT + GRPO on a small Qwen model,
reward = task success minus a cost penalty), and it is the honest answer to
"better planner without a bigger GPU."

## What

- **R1 — trajectory capture**: an agent-side JSONL logger recording every L3
  call (plan/exec/replan) with the full prompt, raw response, parsed output,
  world-state summary, and the deterministic outcome. One new file, zero mod
  changes.
- **R2 — deterministic reward**: reuse `criteria_eval` as the reward — no
  learned reward model. Per-subtask binary success, plan-level mean, a
  schema-validity/format term, and a cost penalty (the local 14B is the
  bottleneck, so verbose/over-decomposed plans are penalized).
- **R3 — offline DPO first**: preference pairs from the archive
  (successful execution = chosen, failed = rejected) via `DPOTrainer` +
  QLoRA. Fast, no live execution, immediately captures "what historically
  worked."
- **R4 — online GRPO**: sample K plans per task from the current policy,
  execute them in headless NeoForge test worlds, reward deterministically,
  optimize with group-relative advantage. This is the exploration phase that
  actually improves beyond the recorded data.
- **R5 — eval + rollout**: a holdout task suite (endurance + war tests), a
  success-rate regression gate, LoRA merge → GGUF → `ollama create` → canary
  on one bot before the fleet.

## Non-goals

- No learned reward model (RLHF-style) — the environment verifier is already
  deterministic and better than a model.
- No cloud training — local weights, local GPUs.
- No change to L2 (stays zero-decision) or to the mod (R1 is agent-side).
- Not training a general model — this tunes *planning for this world*, the
  directive/skill vocabulary, and the persona set.

## Sequencing

R1 (capture) starts immediately and runs in parallel with v10's engine work.
R3 (DPO) can run on the archive as soon as enough captures accumulate. R4
(GRPO) depends on the headless verifier and on v10 having shrunk the
planner's decision space (pick+parameterize a skill), which makes the
exploration problem smaller and denser. **Skills first, RL second** is not
accidental — it is the same lever pulled twice.

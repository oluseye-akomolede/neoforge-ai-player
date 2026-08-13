# v11 tasks — RL fine-tuning of the L3 planner

Sequenced R1→R5; R1 runs in parallel with v10.

## R1 — trajectory capture (agent-side, no mod change)

- [ ] `agent/trajectory_log.py` — JSONL appender on the agent volume.
      Record per L3 call: `{ts, bot, phase(plan|exec|replan), model,
      prompt(full), response(raw), parsed, world_state_summary, outcome}`.
- [ ] Hook `l3_planner.call_plan`/`call_exec`/`call_replan` to log prompt +
      raw response + parsed result before returning.
- [ ] Backfill `outcome` from `criteria_eval` after the subtask settles;
      write the final `plan_status` (complete/failed) on plan close.
- [ ] **Proof**: run one endurance task; confirm a JSONL row exists per L3
      call with non-empty prompt, raw response, and an outcome field that
      matches `criteria_eval`.

## R2 — reward module

- [ ] `agent/rl_reward.py` — `reward(subtask, response, world_state)`:
      deterministic `criteria_eval` result + `schema_valid` term + `λ·cost`
      term. Unit-test against recorded trajectories (reward 1.0 on a known
      pass, 0.0 on a known fail, -1.0 on schema-invalid output).

## R3 — offline DPO (archive)

- [ ] Convert archived plans → TRL DPO dataset: chosen = successful exec
      directives, rejected = failed exec directives, paired on same/near task
      prompt. Filter schema-invalid responses out of the chosen side.
- [ ] Fine-tune `qwen2.5:14b-instruct` with `DPOTrainer` + QLoRA 4-bit +
      unsloth on A4000×2 (bf16).
- [ ] **Proof**: eval the LoRA on the holdout split — plan success rate
      ≥ baseline (no regression) and a win on a known-variance case.

## R4 — online GRPO (headless verifier)

- [ ] Offline replay verifier: evaluate a sampled plan against recorded
      world-state snapshots (fast inner loop).
- [ ] `GRPOTrainer`: sample K plans/task, reward via R2 + replay verifier,
      group-relative advantage. Task set = endurance + war + a seeded set of
      open-ended tasks ("search area, loot, store").
- [ ] Small live-headless validation set in `agent/testing/` (fresh worlds)
      to confirm replay reward correlates with real reward.
- [ ] **Proof**: GRPO checkpoint beats the DPO checkpoint on the holdout
      suite without a cost blow-up.

## R5 — eval, export, canary rollout

- [ ] Holdout suite + reward-drift guard (re-run war-test "criteria
      laundering" case against the fine-tuned model; reject on weakened
      criteria).
- [ ] Merge LoRA → full precision → GGUF Q4_K_M → `ollama create
      qwen2.5:14b-hive-rl` (original tag retained).
- [ ] Point one bot at the new tag via gateway per-client override; observe a
      full endurance cycle.
- [ ] **Proof**: canary bot's success rate ≥ baseline over the cycle; no
      escalation-count regression; then fleet-wide switch.

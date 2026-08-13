#!/usr/bin/env python3
"""Headless proof of rl_reward (v11 R2).

No live server: monkeypatches ``criteria_eval.evaluate`` so the reward's
criteria term is controlled deterministically. Exercises the three spec
anchors — ~1.0 on a pass, ~0.0 on a fail, ≤ -1.0 on schema-invalid — plus the
cost term, the already-parsed trajectory forms, and the plan aggregator.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rl_reward
from plan_schema import Subtask

failures = 0


def check(ok: bool, what: str) -> None:
    global failures
    print(("PASS: " if ok else "FAIL: ") + what)
    if not ok:
        failures += 1


# ── deterministic criteria oracle ──────────────────────────────────────────


def fake_evaluate(bot_name, subtask, last_result_text="", model=None, plan=None):
    met = "PASS" in (subtask.criteria or "")
    return (met, "world_state", "criteria PASS" if met else "criteria FAIL")


rl_reward.criteria_eval.evaluate = fake_evaluate


def sub(criteria: str) -> Subtask:
    return Subtask(id=1, description="t", criteria=criteria)


ws = rl_reward.WorldState(bot_name="bot1")
L = rl_reward.LAMBDA
valid2 = '{"directives": [{"kind": "MINE"}, {"kind": "SMELT"}]}'

# ── known pass: valid 2-directive response, criteria met ───────────────────
r = rl_reward.reward(sub("PASS inventory has 1 iron_ingot"), valid2, ws)
check(r.criteria_met and r.schema_valid and r.cost == 2.0, "pass: criteria_met + schema_valid + cost=2")
check(abs(r.value - (1.0 - L * 2)) < 1e-9, f"pass: reward == 1.0 - λ·2 == {r.value:.4f}")
check(r.value >= 0.9, "pass: reward ~1.0 (anchor)")

# ── known fail: valid response, criteria not met ───────────────────────────
r = rl_reward.reward(sub("FAIL"), valid2, ws)
check((not r.criteria_met) and r.schema_valid, "fail: !criteria_met + schema_valid")
check(abs(r.value - (-L * 2)) < 1e-9, f"fail: reward == -λ·2 == {r.value:.4f}")
check(-0.2 < r.value <= 0.0, "fail: reward ~0.0 (anchor)")

# ── schema-invalid: non-JSON ───────────────────────────────────────────────
bad = "not json at all"
r = rl_reward.reward(sub("FAIL"), bad, ws)
check(not r.schema_valid, "non-JSON: schema_invalid")
check(r.cost == len(bad.split()), "non-JSON: cost == token count")
check(r.value <= -1.0, f"non-JSON: reward <= -1.0 (got {r.value:.4f})")

# ── schema-invalid: empty directives ───────────────────────────────────────
r = rl_reward.reward(sub("FAIL"), '{"directives": []}', ws)
check(not r.schema_valid and r.value <= -1.0, "empty directives: schema_invalid + <= -1.0")

# ── schema-invalid: directive missing kind ─────────────────────────────────
r = rl_reward.reward(sub("FAIL"), '{"directives": [{"target": "iron_ore"}]}', ws)
check(not r.schema_valid, "missing kind: schema_invalid")
check(r.value <= -1.0, "missing kind: reward <= -1.0")

# ── accepts already-parsed list form (trajectory `parsed`) ─────────────────
r = rl_reward.reward(sub("PASS"), [{"kind": "MINE"}], ws)
check(r.schema_valid and r.cost == 1.0, "parsed-list form: schema_valid + cost=1")
r = rl_reward.reward(sub("PASS"), {"directives": [{"kind": "MINE"}]}, ws)
check(r.schema_valid and r.cost == 1.0, "parsed-dict form: schema_valid + cost=1")

# ── world_state coercion + plan aggregator ─────────────────────────────────
r = rl_reward.reward(sub("PASS"), valid2, {"bot_name": "bot2", "last_result_text": "x"})
check(r.criteria_met, "world_state dict coerced")

r_plan = rl_reward.reward_plan([
    rl_reward.reward(sub("PASS"), valid2, ws),
    rl_reward.reward(sub("FAIL"), valid2, ws),
])
check(abs(r_plan - (0.9 + (-0.1)) / 2) < 1e-9, f"reward_plan mean == 0.4 (got {r_plan:.4f})")
check(rl_reward.reward_plan([]) == 0.0, "reward_plan([]) == 0.0")
check(rl_reward.reward_plan([rl_reward.reward(sub("PASS"), valid2, ws)], all_met_bonus=True) == 1.0,
      "reward_plan all_met_bonus == 1.0")

print("\nALL PASS" if failures == 0 else f"\n{failures} FAILURE(S)")
sys.exit(0 if failures == 0 else 1)

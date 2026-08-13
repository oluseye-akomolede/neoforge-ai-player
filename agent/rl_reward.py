"""Deterministic reward for the L3 planner (v11 R2).

Implements design Decision 2:

    R = criteria_met ? 1.0 : 0.0
      + (schema_valid ? 0.0 : -1.0)
      - λ · cost

* ``criteria_met`` — from ``criteria_eval.evaluate``, the SAME oracle the live
  fleet uses (world-state / kill-stat / L1-result; never L3 self-report). The
  L3 fallback strategy is OFF by default here (``model=None``) so the reward
  stays deterministic.
* ``schema_valid`` — the exec response parses to a JSON object with a non-empty
  ``directives`` list, every directive a dict carrying a non-empty ``kind``.
  This mirrors ``l3_planner.call_exec``'s acceptance, but is stricter: a
  directive missing its ``kind`` is penalized here rather than silently
  dropped, because the reward must push the model to stay schema-compliant.
* ``cost`` — number of directives when valid; a whitespace-token estimate of
  the output when invalid. Discourages over-decomposition without starving
  correct plans.
* ``λ`` — 0.05 (module constant, overridable per call).

The returned ``Reward`` is float-coercible (``float(r) == r.value``) so callers
that only need the scalar stay clean; R3/R4 read the breakdown for logging and
advantage computation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import criteria_eval
from plan_schema import Subtask

LAMBDA = 0.05


@dataclass
class WorldState:
    """The minimum world context ``criteria_eval`` needs to score a subtask.

    ``plan`` is optional and only used by the kill-stat strategy (it carries
    the ``kills_at_start`` baseline). ``last_result_text`` feeds the L1
    result-heuristic strategy.
    """

    bot_name: str
    last_result_text: str = ""
    plan: Any = None


@dataclass
class Reward:
    value: float
    criteria_met: bool
    schema_valid: bool
    cost: float
    strategy: str
    reason: str

    def __float__(self) -> float:
        return self.value

    def __repr__(self) -> str:  # pragma: no cover - debug nicety
        return (
            f"Reward(value={self.value:.4f}, criteria_met={self.criteria_met}, "
            f"schema_valid={self.schema_valid}, cost={self.cost:.4f}, "
            f"strategy={self.strategy!r})"
        )


def reward(
    subtask: Subtask,
    response: Any,
    world_state: WorldState | dict | None = None,
    *,
    lam: float = LAMBDA,
    model: str | None = None,
) -> Reward:
    """Score one subtask-execution turn.

    ``response`` is the raw model output string, an already-parsed
    ``{"directives": [...]}`` object, or the filtered ``parsed`` list from a
    trajectory record — all three resolve to the same ``schema_valid``/``cost``
    decision. ``world_state`` carries the context ``criteria_eval`` needs;
    pass ``model`` only to opt back into the L3 fallback (not for training).
    """
    ws = _coerce_world_state(world_state)
    schema_valid, directives = _parse_exec(response)

    # Deterministic oracle by default (model=None → no L3 fallback).
    satisfied, strategy, reason = criteria_eval.evaluate(
        ws.bot_name,
        subtask,
        last_result_text=ws.last_result_text,
        model=model,
        plan=ws.plan,
    )

    cost = float(len(directives)) if schema_valid else float(_token_estimate(response))
    value = (1.0 if satisfied else 0.0) + (0.0 if schema_valid else -1.0) - lam * cost
    return Reward(
        value=value,
        criteria_met=satisfied,
        schema_valid=schema_valid,
        cost=cost,
        strategy=strategy,
        reason=reason,
    )


def reward_plan(rewards: list[Reward], *, all_met_bonus: bool = False) -> float:
    """Aggregate per-subtask rewards for a plan turn (Decision 2).

    Defaults to the mean subtask reward. With ``all_met_bonus``, returns 1.0
    iff every subtask's criteria were met (the design's alternative).
    """
    if not rewards:
        return 0.0
    if all_met_bonus and all(r.criteria_met for r in rewards):
        return 1.0
    return sum(r.value for r in rewards) / len(rewards)


# ── internals ──────────────────────────────────────────────────────────────


def _parse_exec(response: Any) -> tuple[bool, list[dict[str, Any]]]:
    """Return ``(schema_valid, directives)``.

    Accepts a raw string (parsed here), a ``{"directives": [...]}`` object, or
    the filtered ``parsed`` list. Valid iff the directives form a non-empty
    list of dicts each carrying a non-empty ``kind``.
    """
    obj: Any = response
    if isinstance(response, str):
        try:
            obj = json.loads(response)
        except json.JSONDecodeError:
            return False, []

    if isinstance(obj, list):
        directives = obj
    elif isinstance(obj, dict):
        directives = obj.get("directives")
    else:
        return False, []

    if not isinstance(directives, list) or not directives:
        return False, []

    out: list[dict[str, Any]] = []
    for d in directives:
        if not isinstance(d, dict) or not isinstance(d.get("kind"), str) or not d["kind"]:
            return False, []
        out.append(d)
    return True, out


def _token_estimate(response: Any) -> int:
    """Whitespace-token count of the output — the cost term for invalid output."""
    if isinstance(response, str):
        text = response
    else:
        try:
            text = json.dumps(response)
        except TypeError:
            text = str(response)
    return len(text.split())


def _coerce_world_state(world_state: WorldState | dict | None) -> WorldState:
    if isinstance(world_state, WorldState):
        return world_state
    if isinstance(world_state, dict):
        return WorldState(
            bot_name=str(world_state.get("bot_name", "")),
            last_result_text=str(world_state.get("last_result_text", "")),
            plan=world_state.get("plan"),
        )
    raise TypeError(
        f"world_state must be WorldState or dict, got {type(world_state).__name__}"
    )

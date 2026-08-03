"""Three-strategy criteria evaluator for subtask completion (aiplayer-mod).

Strategy 1: world-state query — bot inventory / position / nearby blocks via mod API
Strategy 2: L1 result heuristic — match the criterion string against the last
            directive's result string
Strategy 3: L3 fallback — yes/no LLM judgment

L2 picks the first conclusive answer.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

import api
from brain import ollama_lock
from config import MOD_API_URL, OLLAMA_URL
from plan_schema import Subtask

log = logging.getLogger("aibot.criteria")


_INVENTORY_PATTERN = re.compile(
    r"inventory\s+(?:has|contains)\s+(?:at\s+least\s+)?(\d+)\s+([a-z0-9_:]+)",
    re.IGNORECASE,
)
_POSITION_PATTERN = re.compile(
    r"(?:bot|at)\s*\(?\s*(-?\d+)[,\s]+(-?\d+)[,\s]+(-?\d+)",
    re.IGNORECASE,
)
_BLOCK_PATTERN = re.compile(
    r"block\s+at\s*\(?\s*(-?\d+)[,\s]+(-?\d+)[,\s]+(-?\d+)\)?\s+is\s+([a-z0-9_:]+)",
    re.IGNORECASE,
)


def evaluate(bot_name: str, subtask: Subtask,
             last_result_text: str = "",
             model: str | None = None,
             plan=None) -> tuple[bool, str, str]:
    """
    Return (satisfied, strategy, reason).
      strategy ∈ {"world_state", "result_text", "l3_fallback", "inconclusive"}
    """
    s1 = _strategy_world_state(bot_name, subtask)
    if s1 is not None:
        return s1[0], "world_state", s1[1]

    sk = _strategy_kills(bot_name, subtask, plan)
    if sk is not None:
        return sk[0], "kill_stat", sk[1]

    s2 = _strategy_result_text(subtask, last_result_text)
    if s2 is not None:
        return s2[0], "result_text", s2[1]

    if model:
        s3 = _strategy_l3_fallback(model, bot_name, subtask, last_result_text)
        if s3 is not None:
            return s3[0], "l3_fallback", s3[1]

    return False, "inconclusive", "no strategy could decide"


# ── Strategy 1: world-state ────────────────────────────────────────────────


_CLAUSE_SPLIT = re.compile(r"\s+(?:AND|and)\s+|\s*&&\s*")

# Fail-open copy of l2-mcp's material synonyms: criteria written with
# invented ids must check the REAL item the (normalized) directives deliver
# (round-8 redemption finding: criterion "quartz_ore" vs delivered
# "nether_quartz_ore" could never match).
ITEM_SYNONYMS = {
    "minecraft:quartz_ore": "minecraft:nether_quartz_ore",
    "minecraft:soul_sand_gravel": "minecraft:soul_sand",
    "minecraft:soul_gravel": "minecraft:soul_sand",
    "minecraft:nether_gravel": "minecraft:gravel",
    "minecraft:nether_stone": "minecraft:netherrack",
    "minecraft:nether_rock": "minecraft:netherrack",
    "minecraft:quartz_stone": "minecraft:quartz_block",
    "minecraft:smooth_quartz_block": "minecraft:smooth_quartz",
    "minecraft:basalt_stone": "minecraft:basalt",
    "minecraft:blackstone_block": "minecraft:blackstone",
}


def _strategy_world_state(bot_name: str, subtask: Subtask) -> tuple[bool, str] | None:
    """Evaluate EVERY checkable clause of the criterion against the mod API
    (war-game findings B2/B3: the old paths 404'd so this never ran, and
    compound AND criteria were judged by their first clause only).

    Any checkable clause failing -> False. All clauses checkable and passing
    -> True. Otherwise (nothing checkable / a passing subset) -> None so the
    remaining strategies can weigh in.
    """
    criterion = subtask.criteria or ""
    clauses = [c.strip() for c in _CLAUSE_SPLIT.split(criterion) if c.strip()]
    if not clauses:
        return None

    results: list[tuple[bool, str]] = []
    unchecked = 0
    for clause in clauses:
        r = _eval_clause(bot_name, clause)
        if r is None:
            unchecked += 1
        else:
            results.append(r)
            if not r[0]:
                return False, r[1]

    if results and unchecked == 0:
        return True, "; ".join(reason for _, reason in results)
    return None


def _eval_clause(bot_name: str, clause: str) -> tuple[bool, str] | None:
    # Block-at check (before position: "block at (x,y,z)" also matches
    # the position pattern)
    m = _BLOCK_PATTERN.search(clause)
    if m:
        bx, by, bz = int(m.group(1)), int(m.group(2)), int(m.group(3))
        want = m.group(4)
        if ":" not in want:
            want = f"minecraft:{want}"
        try:
            got = api.block_at(bot_name, bx, by, bz).get("block", "")
            return (got == want, f"block at ({bx},{by},{bz}) is {got} (wanted {want})")
        except Exception as e:
            log.debug("block query failed: %s", e)
            return None

    # Inventory check
    m = _INVENTORY_PATTERN.search(clause)
    if m:
        need = int(m.group(1))
        item_id = m.group(2)
        if ":" not in item_id:
            item_id = f"minecraft:{item_id}"
        item_id = ITEM_SYNONYMS.get(item_id, item_id)
        try:
            data = api.inventory(bot_name)
            count = 0
            for slot in data.get("inventory", []):
                if slot.get("item") == item_id:
                    count += int(slot.get("count", 0))
            ok = count >= need
            return ok, f"inventory has {count}/{need} of {item_id}"
        except Exception as e:
            log.debug("inventory query failed: %s", e)
            return None

    # Position check
    m = _POSITION_PATTERN.search(clause)
    if m and "block at" not in clause.lower():
        tx, ty, tz = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            pos = api.status(bot_name).get("position", {})
            dx = abs(int(pos.get("x", 0)) - tx)
            dy = abs(int(pos.get("y", 0)) - ty)
            dz = abs(int(pos.get("z", 0)) - tz)
            ok = (dx + dy + dz) <= 3   # tolerance
            return ok, f"bot at ({pos.get('x'):.0f},{pos.get('y'):.0f},{pos.get('z'):.0f}) vs target ({tx},{ty},{tz})"
        except Exception as e:
            log.debug("position query failed: %s", e)
            return None

    # Dimension check
    m = re.search(r"in\s+dimension\s+([a-z0-9_:]+)", clause, re.IGNORECASE)
    if m:
        want_dim = m.group(1)
        if ":" not in want_dim:
            want_dim = f"minecraft:{want_dim}"
        try:
            got_dim = api.status(bot_name).get("dimension", "")
            return (got_dim == want_dim, f"bot in {got_dim} (wanted {want_dim})")
        except Exception as e:
            log.debug("dimension query failed: %s", e)
            return None

    return None


# ── Strategy 1b: kill-count check ──────────────────────────────────────────
# "slay 200 enemies", "killed 200 enemies", "kills has value 200", "200 kills".
# Checked as a DELTA against plan.meta["kills_at_start"] using the mod's
# lifetime mob_kills stat. War-test finding #1: unverifiable kill criteria
# were passing via lax LLM judgment.

_KILLS_PATTERNS = [
    re.compile(r"(?:kill|slay|slain|defeat|eliminat|dispatch|vanquish|destroy)\w*"
               r"(?:\s+\w+){0,3}?\s+(?:at\s+least\s+)?(\d+)", re.IGNORECASE),
    re.compile(r"kills?\s+(?:has\s+value|reach(?:es)?|count(?:\s+of)?|[:=><]+)\s*(\d+)", re.IGNORECASE),
    re.compile(r"(\d+)\s+(?:combat\s+)?(?:kills|eliminations|enem(?:y|ies)|mobs?|hostiles?|foes)\b",
               re.IGNORECASE),
]


def _strategy_kills(bot_name: str, subtask: Subtask, plan) -> tuple[bool, str] | None:
    criterion = subtask.criteria or ""
    target = None
    for pat in _KILLS_PATTERNS:
        m = pat.search(criterion)
        if m:
            target = int(m.group(1))
            break
    if target is None:
        return None
    baseline = None
    if plan is not None and isinstance(getattr(plan, "meta", None), dict):
        baseline = plan.meta.get("kills_at_start")
    try:
        st = api.status(bot_name)
        current = st.get("mob_kills")
        if not isinstance(current, int) or current < 0:
            return None  # mod without the stat — let other strategies decide
    except Exception as e:
        log.debug("kill-stat query failed: %s", e)
        return None
    if baseline is None:
        # No baseline captured (old plan / API blip at start): can only report
        # progress against lifetime count — too ambiguous to auto-pass. Fail
        # conservatively with the observed number so retries/replans see it.
        return False, f"kill target {target}: no baseline; lifetime mob_kills={current}"
    delta = current - int(baseline)
    ok = delta >= target
    return ok, f"kills this plan: {delta}/{target} (lifetime {current})"


# ── Strategy 2: result text heuristic ──────────────────────────────────────


_FAILURE_TOKENS = ("FAILED", "ERROR", "TIMEOUT", "ABORTED")
_SUCCESS_TOKENS = ("COMPLETED", "DONE", "SUCCESS")


def _strategy_result_text(subtask: Subtask, last_result_text: str) -> tuple[bool, str] | None:
    if not last_result_text:
        return None
    upper = last_result_text.upper()
    if any(tok in upper for tok in _FAILURE_TOKENS):
        return False, f"last directive result contained failure token"
    if any(tok in upper for tok in _SUCCESS_TOKENS):
        return True, f"last directive result contained success token"
    return None


# ── Strategy 3: L3 fallback ────────────────────────────────────────────────


_FALLBACK_PROMPT = """You are an evaluator. Given a subtask's completion criterion and
the most recent execution evidence, judge whether the criterion is satisfied.

Output ONLY JSON: {"satisfied": true|false, "reason": "<short>"}
No prose, no fences.

Criterion: {criterion}
Subtask description: {description}
Most recent result: {result}
"""


def _strategy_l3_fallback(model: str, bot_name: str, subtask: Subtask,
                           last_result: str) -> tuple[bool, str] | None:
    prompt = _FALLBACK_PROMPT.format(
        criterion=subtask.criteria,
        description=subtask.description,
        result=last_result[:500],
    )
    try:
        with ollama_lock:
            r = requests.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": "Judge."},
                    ],
                    "stream": False,
                    "options": {"temperature": 0.0, "num_predict": 128},
                },
                timeout=60,
            )
        r.raise_for_status()
        raw = r.json()["message"]["content"].strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.rstrip().endswith("```"):
                raw = raw.rstrip()[:-3]
        data = json.loads(raw.strip())
    except Exception as e:
        log.warning("L3 fallback eval failed: %s", e)
        return None
    if not isinstance(data, dict) or "satisfied" not in data:
        return None
    return bool(data["satisfied"]), str(data.get("reason", ""))

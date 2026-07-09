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


def _strategy_world_state(bot_name: str, subtask: Subtask) -> tuple[bool, str] | None:
    criterion = subtask.criteria or ""

    # Inventory check
    m = _INVENTORY_PATTERN.search(criterion)
    if m:
        need = int(m.group(1))
        item_id = m.group(2)
        if ":" not in item_id:
            item_id = f"minecraft:{item_id}"
        try:
            r = requests.get(f"{MOD_API_URL}/inventory", params={"bot": bot_name}, timeout=8)
            r.raise_for_status()
            data = r.json()
            count = 0
            for slot in data.get("items", []):
                if slot.get("id") == item_id:
                    count += int(slot.get("count", 0))
            ok = count >= need
            return ok, f"inventory has {count}/{need} of {item_id}"
        except Exception as e:
            log.debug("inventory query failed: %s", e)
            return None

    # Position check
    m = _POSITION_PATTERN.search(criterion)
    if m and "block at" not in criterion.lower():
        tx, ty, tz = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            r = requests.get(f"{MOD_API_URL}/position", params={"bot": bot_name}, timeout=8)
            r.raise_for_status()
            pos = r.json()
            dx = abs(int(pos.get("x", 0)) - tx)
            dy = abs(int(pos.get("y", 0)) - ty)
            dz = abs(int(pos.get("z", 0)) - tz)
            ok = (dx + dy + dz) <= 3   # tolerance
            return ok, f"bot at ({pos.get('x')},{pos.get('y')},{pos.get('z')}) vs target ({tx},{ty},{tz})"
        except Exception as e:
            log.debug("position query failed: %s", e)
            return None

    # Block-at check
    m = _BLOCK_PATTERN.search(criterion)
    if m:
        bx, by, bz = int(m.group(1)), int(m.group(2)), int(m.group(3))
        want = m.group(4)
        if ":" not in want:
            want = f"minecraft:{want}"
        try:
            r = requests.get(
                f"{MOD_API_URL}/block",
                params={"x": bx, "y": by, "z": bz},
                timeout=8,
            )
            r.raise_for_status()
            got = r.json().get("id", "")
            return (got == want, f"block at ({bx},{by},{bz}) is {got} (wanted {want})")
        except Exception as e:
            log.debug("block query failed: %s", e)
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

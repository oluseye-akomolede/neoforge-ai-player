"""Plan-template memory.

Reuse archived SUCCESSFUL plans for near-identical tasks: "mine 24 oak logs"
can replay the proven plan from "mine 12 oak logs" with the count substituted
— zero L3 calls, because the cloned subtasks carry the pre-baked directives
that worked last time (plan_orchestrator dispatches those without an EXEC
call on attempt 0, and retries fall through to L3 as usual).

Deliberately conservative — a wrong reuse costs more than a slow plan:
  - Reuse only on EXACT normalized-text match (numbers masked to '#').
  - Count substitution only when BOTH tasks contain exactly one number.
  - Plans whose directives or criteria embed absolute coordinates are never
    reused (positional plans are context-dependent).
  - Only plans that finished status=complete, with directives on every
    subtask, are indexed.

Index is per-bot (personas plan differently) and built lazily from the
archive directory; completed plans are appended live via record().

Kill switch: PLAN_MEMORY_ENABLED=false.
"""
from __future__ import annotations

import copy
import datetime
import json
import logging
import os
import re

import plan_store
from plan_schema import Plan

log = logging.getLogger("aibot.plan-memory")

ENABLED = os.getenv("PLAN_MEMORY_ENABLED", "true").lower() in ("true", "1", "yes")
MAX_INDEX_FILES = 300

_NUM_RE = re.compile(r"\b\d+\b")
_COORD_RE = re.compile(r"\(\s*-?\d+\s*[,\s]\s*-?\d+\s*[,\s]\s*-?\d+\s*\)")

# (bot, normalized_task) -> {"plan": <dict>, "nums": [int, ...]}
_index: dict[tuple[str, str], dict] | None = None


def _normalize(task: str) -> tuple[str, list[int]]:
    t = task.strip().lower()
    t = re.sub(r"[^\w\s#-]", " ", t)
    nums = [int(m) for m in _NUM_RE.findall(t)]
    norm = _NUM_RE.sub("#", t)
    norm = re.sub(r"\s+", " ", norm).strip()
    return norm, nums


def _reusable(pd: dict) -> bool:
    """Is this archived plan dict safe to replay?"""
    if pd.get("status") != "complete":
        return False
    subtasks = pd.get("subtasks") or []
    if not subtasks:
        return False
    for s in subtasks:
        dirs = s.get("directives") or []
        if not dirs:
            return False  # nothing pre-baked → replay has no value
        for d in dirs:
            if any(k in d for k in ("x", "y", "z")):
                return False  # positional — context-dependent
        if _COORD_RE.search(s.get("criteria", "")):
            return False
    return True


def _build_index() -> None:
    global _index
    _index = {}
    try:
        files = sorted(plan_store.ARCHIVE.glob("*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)[:MAX_INDEX_FILES]
    except Exception:
        files = []
    for p in files:
        try:
            pd = json.loads(p.read_text())
        except Exception:
            continue
        if not _reusable(pd):
            continue
        bot = pd.get("bot", "")
        norm, nums = _normalize(pd.get("task", ""))
        key = (bot, norm)
        if key not in _index:  # newest wins (list is mtime-desc)
            _index[key] = {"plan": pd, "nums": nums}
    log.info("plan-memory index built: %d reusable template(s)", len(_index))


def _substitute_count(pd: dict, old: int, new: int) -> dict:
    """Replace the count `old` with `new` in criteria strings and directive
    count fields. Word-boundary exact matches only."""
    out = copy.deepcopy(pd)
    pat = re.compile(rf"\b{old}\b")
    for s in out.get("subtasks", []):
        if s.get("criteria"):
            s["criteria"] = pat.sub(str(new), s["criteria"])
        if s.get("description"):
            s["description"] = pat.sub(str(new), s["description"])
        for d in s.get("directives", []):
            if d.get("count") == old:
                d["count"] = new
    return out


def lookup(bot_name: str, task: str) -> Plan | None:
    """Return a fresh Plan cloned from a successful archived template, or None."""
    if not ENABLED:
        return None
    global _index
    if _index is None:
        _build_index()
    norm, nums = _normalize(task)
    entry = _index.get((bot_name, norm))
    if entry is None:
        return None

    pd = entry["plan"]
    old_nums = entry["nums"]
    if nums != old_nums:
        if len(nums) == 1 and len(old_nums) == 1:
            pd = _substitute_count(pd, old_nums[0], nums[0])
        else:
            return None  # ambiguous substitution — let L3 plan it

    clone = copy.deepcopy(pd)
    clone["task"] = task
    clone["bot"] = bot_name
    clone["created_at"] = datetime.datetime.utcnow().isoformat()
    clone["status"] = "executing"
    for s in clone.get("subtasks", []):
        s["status"] = "pending"
        s["attempts"] = 0
        s["replans"] = 0
        s["error"] = None
        # directives stay — that's the pre-baked replay
    clone["current_subtask_id"] = min(s["id"] for s in clone["subtasks"])
    log.info("[%s] plan-memory reuse: %r (template from archive, %d subtasks)",
             bot_name, norm, len(clone["subtasks"]))
    return Plan.from_dict(clone)


def record(plan: Plan) -> None:
    """Index a just-completed plan for future reuse."""
    if not ENABLED:
        return
    global _index
    if _index is None:
        _build_index()
    pd = plan.to_dict()
    if not _reusable(pd):
        return
    norm, nums = _normalize(plan.task)
    _index[(plan.bot, norm)] = {"plan": pd, "nums": nums}
    log.info("[%s] plan-memory recorded template: %r", plan.bot, norm)

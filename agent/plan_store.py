"""On-disk persistence for L3 spec-driven plans.

Layout:
  agent_plans/<bot>_current.json   — active plan (at most one per bot)
  agent_plans/archive/             — completed/failed plans (rotated)

Root is configurable via env var AIBOT_PLANS_DIR (defaults to ./agent_plans
relative to PROFILE_PATH's containing dir).
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import time

from plan_schema import Plan

log = logging.getLogger("aibot.plans")

# Default: sibling of the agent's data directory
_default = os.path.join(
    os.path.dirname(os.getenv("PROFILE_PATH", os.path.dirname(__file__))),
    "agent_plans",
)
ROOT = pathlib.Path(os.getenv("AIBOT_PLANS_DIR", _default))
ARCHIVE = ROOT / "archive"


def ensure_dirs() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    ARCHIVE.mkdir(parents=True, exist_ok=True)


def _current_path(bot: str) -> pathlib.Path:
    return ROOT / f"{bot}_current.json"


def write(plan: Plan) -> pathlib.Path:
    ensure_dirs()
    p = _current_path(plan.bot)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
    tmp.replace(p)
    return p


def read(bot: str) -> Plan | None:
    p = _current_path(bot)
    if not p.exists():
        return None
    try:
        return Plan.from_dict(json.loads(p.read_text()))
    except Exception:
        log.exception("failed to read plan for %s", bot)
        return None


def archive(plan: Plan) -> pathlib.Path | None:
    ensure_dirs()
    src = _current_path(plan.bot)
    ts = int(time.time())
    dst = ARCHIVE / f"{plan.bot}_{ts}.json"
    if src.exists():
        src.replace(dst)
    else:
        dst.write_text(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
    return dst


def has_active(bot: str) -> bool:
    return _current_path(bot).exists()


def list_active() -> list[dict]:
    ensure_dirs()
    out = []
    for p in sorted(ROOT.glob("*_current.json")):
        try:
            data = json.loads(p.read_text())
        except Exception:
            continue
        subs = data.get("subtasks", [])
        cur_id = data.get("current_subtask_id", 1)
        cur = next((s for s in subs if s.get("id") == cur_id), None)
        out.append({
            "file": p.name,
            "bot": data.get("bot"),
            "task": data.get("task", "")[:120],
            "status": data.get("status"),
            "subtask_count": len(subs),
            "current_subtask_id": cur_id,
            "current_subtask_desc": (cur or {}).get("description", "")[:120] if cur else "",
            "current_attempts": (cur or {}).get("attempts", 0) if cur else 0,
            "complete_count": sum(1 for s in subs if s.get("status") == "complete"),
        })
    return out


def get_full(bot: str) -> dict | None:
    p = _current_path(bot)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        log.exception("failed to read plan for %s", bot)
        return None


def list_archive(limit: int = 50) -> list[dict]:
    ensure_dirs()
    files = sorted(ARCHIVE.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for p in files[:limit]:
        try:
            data = json.loads(p.read_text())
        except Exception:
            continue
        out.append({
            "file": p.name,
            "archived_at_mtime": p.stat().st_mtime,
            "bot": data.get("bot"),
            "status": data.get("status"),
            "subtask_count": len(data.get("subtasks", [])),
            "task": data.get("task", "")[:120],
        })
    return out

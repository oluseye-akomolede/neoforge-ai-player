"""Append-only trajectory logger for RL (v11 R1).

Records every L3 planner call — plan / exec / replan — as an append-only
JSONL stream so the RL pass (R2→R5) has the raw `(prompt → response → outcome)`
triples the archive alone can't provide. The plan archive stores the *parsed*
plan; this stores the exact prompt and the verbatim model output.

Two-record design (append-only means never rewriting a line):
  - a "call" record is written immediately (crash-safe) with prompt, raw
    response, parsed output, and world-state summary
  - an "outcome" record is written later, once `criteria_eval` settles the
    subtask, correlated to its call by `call_id`
  - a "plan_close" record carries the terminal plan status

The RL training reader joins call → outcome on `call_id`. Logging is
best-effort: a full disk or a write error must never break the bot.

Layout (configurable via AIBOT_TRAJECTORY_DIR):
  agent_trajectories/trajectory-YYYY-MM-DD.jsonl
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import pathlib
import threading
import uuid

log = logging.getLogger("aibot.trajectory")

# Default: sibling of the agent's data directory (mirrors plan_store's layout)
_default = os.path.join(
    os.path.dirname(os.getenv("PROFILE_PATH", os.path.dirname(__file__))),
    "agent_trajectories",
)
DIR = pathlib.Path(os.getenv("AIBOT_TRAJECTORY_DIR", _default))

# Fleet bots run in separate threads; the lock keeps JSONL lines from
# interleaving mid-line across concurrent appends.
_lock = threading.Lock()


def _path() -> pathlib.Path:
    day = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    return DIR / f"trajectory-{day}.jsonl"


def _append(record: dict) -> None:
    """Best-effort JSONL append. Never raises."""
    try:
        DIR.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, sort_keys=True, default=str)
        with _lock:
            with open(_path(), "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
    except Exception:
        log.exception("trajectory append failed (non-fatal)")


def log_call(
    *,
    phase: str,
    bot: str,
    model: str,
    prompt_system: str,
    prompt_user: str,
    response_raw: str,
    parsed,
    world_state_summary: str = "",
    plan_ref: str | None = None,
    subtask_id: int | None = None,
    parse_error: str | None = None,
) -> str:
    """Record one L3 call. Returns the call_id a later outcome must cite."""
    call_id = uuid.uuid4().hex
    _append({
        "type": "call",
        "call_id": call_id,
        "ts": datetime.datetime.utcnow().isoformat(),
        "phase": phase,
        "bot": bot,
        "model": model,
        "plan_ref": plan_ref,
        "subtask_id": subtask_id,
        "prompt_system": prompt_system,
        "prompt_user": prompt_user,
        "response_raw": response_raw,
        "parsed": parsed,
        "parse_error": parse_error,
        "world_state_summary": world_state_summary,
    })
    return call_id


def log_outcome(
    *,
    call_id: str,
    bot: str,
    phase: str,
    satisfied: bool,
    strategy: str,
    reason: str,
    plan_ref: str | None = None,
    subtask_id: int | None = None,
) -> None:
    """Record the deterministic `criteria_eval` result for a prior call."""
    _append({
        "type": "outcome",
        "call_id": call_id,
        "ts": datetime.datetime.utcnow().isoformat(),
        "phase": phase,
        "bot": bot,
        "plan_ref": plan_ref,
        "subtask_id": subtask_id,
        "satisfied": bool(satisfied),
        "strategy": strategy,
        "reason": reason,
    })


def log_plan_close(
    *,
    bot: str,
    plan_ref: str,
    status: str,
    task: str,
    subtasks_total: int,
    subtasks_complete: int,
) -> None:
    """Record the terminal plan status once the plan settles."""
    _append({
        "type": "plan_close",
        "ts": datetime.datetime.utcnow().isoformat(),
        "bot": bot,
        "plan_ref": plan_ref,
        "status": status,
        "task": task,
        "subtasks_total": subtasks_total,
        "subtasks_complete": subtasks_complete,
    })

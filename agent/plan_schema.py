"""Plan schema + validation for the L3 spec-driven planning layer.

A plan is the single source of truth for a single bot's task execution.
L3 produces it once in Phase 1; L2 (the agent main loop) mutates it on every
state transition (subtask complete, retry, replan).
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field, asdict
from typing import Any, Literal

PlanStatus = Literal["planning", "executing", "complete", "failed", "cancelled"]
SubtaskStatus = Literal["pending", "executing", "complete", "failed"]


@dataclass
class Subtask:
    id: int
    description: str
    criteria: str
    status: SubtaskStatus = "pending"
    directives: list[dict[str, Any]] = field(default_factory=list)
    attempts: int = 0
    replans: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Subtask":
        return cls(
            id=int(d["id"]),
            description=str(d.get("description", "")),
            criteria=str(d.get("criteria", "")),
            status=d.get("status", "pending"),
            directives=list(d.get("directives", [])),
            attempts=int(d.get("attempts", 0)),
            replans=int(d.get("replans", 0)),
            error=d.get("error"),
        )


@dataclass
class Plan:
    task: str
    bot: str
    created_at: str
    status: PlanStatus
    subtasks: list[Subtask]
    current_subtask_id: int
    # Free-form execution metadata (e.g. kills_at_start baseline for
    # "killed N enemies" criteria). Persisted with the plan.
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "bot": self.bot,
            "created_at": self.created_at,
            "status": self.status,
            "subtasks": [s.to_dict() for s in self.subtasks],
            "current_subtask_id": self.current_subtask_id,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Plan":
        return cls(
            task=str(d["task"]),
            bot=str(d["bot"]),
            created_at=str(d.get("created_at") or datetime.datetime.utcnow().isoformat()),
            status=d.get("status", "executing"),
            subtasks=[Subtask.from_dict(s) for s in d.get("subtasks", [])],
            current_subtask_id=int(d.get("current_subtask_id", 1)),
            meta=dict(d.get("meta") or {}),
        )

    def current_subtask(self) -> Subtask | None:
        for s in self.subtasks:
            if s.id == self.current_subtask_id:
                return s
        return None

    def all_complete(self) -> bool:
        return all(s.status == "complete" for s in self.subtasks)

    def advance(self) -> None:
        for s in self.subtasks:
            if s.id > self.current_subtask_id and s.status in ("pending", "executing"):
                self.current_subtask_id = s.id
                return
        if self.all_complete():
            self.status = "complete"


class PlanValidationError(ValueError):
    pass


def _signals_a_script(d: dict) -> bool:
    """Whether this plan reply is asking for a script rather than a step list.

    A goal that never finishes on its own -- "tell me when it gets dark", "keep
    the furnace fed" -- has no natural subtasks. Requiring one makes the model
    either fabricate a step or omit the field and fail validation; both were
    seen for the SAME goal (TEST 12:25:50Z produced a 1-subtask plan and
    reached the SCRIPT call; PROD 12:21:56Z answered "plan missing required
    field: subtasks" and no SCRIPT call was made).

    Either signal counts: the explicit `wants_script: true`, or a fenced
    `script` field, since the prompt has asked for both shapes and a model
    following the older wording emits the latter.
    """
    if not isinstance(d, dict):
        return False
    if d.get("wants_script") is True:
        return True
    script = d.get("script")
    return isinstance(script, str) and bool(script.strip())


def validate_plan_dict(d: Any, goal: str | None = None) -> None:
    if not isinstance(d, dict):
        raise PlanValidationError("plan must be a JSON object")
    # A script reply need not echo the goal back as `task`. The model omits it
    # sometimes, and prod Mystic (2026-11-22 12:55-13:00Z, try 1) failed a
    # complete plan on "plan missing required field: task". The goal text is
    # already known to the caller, so it is filled in rather than demanded
    # twice. A step-list reply keeps the full contract: there, `task` is the
    # ordinary case and a missing one is a real model error.
    #
    # `d` is mutated, not copied: the caller reads `data["task"]` when it
    # builds the Plan (l3_planner.py:614), so a fill that only satisfied this
    # function would validate and then KeyError one line later.
    script_plan = _signals_a_script(d)
    if "task" not in d:
        if script_plan and goal:
            d["task"] = goal
        else:
            raise PlanValidationError("plan missing required field: task")
    # Subtasks are required only for a STEP LIST. A reply that signals a script
    # may legitimately carry none, and rejecting it failed a goal that never
    # needed steps at all. A reply that signals NO script keeps the full
    # contract: a steppable goal with no steps is a broken plan, and accepting
    # it would dispatch nothing while looking successful.
    if "subtasks" not in d:
        if script_plan:
            return
        raise PlanValidationError("plan missing required field: subtasks")
    subs = d.get("subtasks")
    if not isinstance(subs, list) or not subs:
        if script_plan:
            # Absent steps are fine for a script, but a PRESENT malformed
            # `subtasks` is a model error either way and must not slip
            # through unread: only an empty list is excused here.
            if subs not in (None, []):
                raise PlanValidationError(
                    "plan.subtasks must be a list, got %r" % (subs,))
            return
        raise PlanValidationError("plan.subtasks must be a non-empty list")
    seen = set()
    for s in subs:
        if not isinstance(s, dict):
            raise PlanValidationError("each subtask must be a JSON object")
        for f in ("id", "description", "criteria"):
            if f not in s:
                raise PlanValidationError(f"subtask missing required field: {f}")
        sid = s["id"]
        if not isinstance(sid, int) or sid < 1:
            raise PlanValidationError(f"subtask.id must be positive int, got {sid!r}")
        if sid in seen:
            raise PlanValidationError(f"duplicate subtask id: {sid}")
        seen.add(sid)


def validate_subtask_dict(d: Any) -> None:
    if not isinstance(d, dict):
        raise PlanValidationError("subtask must be a JSON object")
    for f in ("id", "description", "criteria"):
        if f not in d:
            raise PlanValidationError(f"subtask missing required field: {f}")
    if not isinstance(d["id"], int) or d["id"] < 1:
        raise PlanValidationError("subtask.id must be positive int")

"""Plan schema + validation for the L3 spec-driven planning layer.

A plan is the single source of truth for a single bot's task execution.
L3 produces it once in Phase 1; L2 (the agent main loop) mutates it on every
state transition (subtask complete, retry, replan).
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field, asdict
from typing import Any, Literal

PlanStatus = Literal["planning", "executing", "complete", "failed"]
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "bot": self.bot,
            "created_at": self.created_at,
            "status": self.status,
            "subtasks": [s.to_dict() for s in self.subtasks],
            "current_subtask_id": self.current_subtask_id,
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


def validate_plan_dict(d: Any) -> None:
    if not isinstance(d, dict):
        raise PlanValidationError("plan must be a JSON object")
    for req in ("task", "subtasks"):
        if req not in d:
            raise PlanValidationError(f"plan missing required field: {req}")
    subs = d.get("subtasks")
    if not isinstance(subs, list) or not subs:
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

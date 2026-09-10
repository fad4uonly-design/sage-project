"""Planning domain models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso


class GoalStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class PlanStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class Goal(BaseModel):
    id: str = Field(default_factory=lambda: new_id("goal"))
    description: str
    status: GoalStatus = GoalStatus.ACTIVE
    priority: float = Field(default=0.5, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utcnow_iso)
    updated_at: str = Field(default_factory=utcnow_iso)
    completed_at: str | None = None


class PlanStep(BaseModel):
    index: int
    title: str
    detail: str = ""
    status: TaskStatus = TaskStatus.PENDING


class Plan(BaseModel):
    id: str = Field(default_factory=lambda: new_id("plan"))
    goal_id: str | None = None
    title: str
    status: PlanStatus = PlanStatus.DRAFT
    steps: list[PlanStep] = Field(default_factory=list)
    created_at: str = Field(default_factory=utcnow_iso)
    updated_at: str = Field(default_factory=utcnow_iso)


class Task(BaseModel):
    id: str = Field(default_factory=lambda: new_id("task"))
    plan_id: str | None = None
    title: str
    status: TaskStatus = TaskStatus.PENDING
    priority: float = Field(default=0.5, ge=0.0, le=1.0)
    due_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utcnow_iso)
    updated_at: str = Field(default_factory=utcnow_iso)


class PlanProgress(BaseModel):
    plan_id: str
    status: PlanStatus
    total_steps: int
    done_steps: int
    percent_complete: float

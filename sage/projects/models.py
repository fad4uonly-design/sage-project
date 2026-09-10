"""Project domain models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ProjectLinkType(StrEnum):
    DOCUMENT = "document"
    MEMORY = "memory"
    GOAL = "goal"
    WORKFLOW = "workflow"
    DECISION = "decision"
    MEETING = "meeting"
    NOTE = "note"
    RISK = "risk"
    ENTITY = "entity"
    TASK = "task"
    FILE = "file"


class Project(BaseModel):
    id: str = Field(default_factory=lambda: new_id("proj"))
    name: str
    description: str = ""
    status: ProjectStatus = ProjectStatus.ACTIVE
    priority: float = Field(default=0.5, ge=0.0, le=1.0)
    domain: str | None = None
    objectives: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    created_at: str = Field(default_factory=utcnow_iso)
    updated_at: str = Field(default_factory=utcnow_iso)
    completed_at: str | None = None
    last_accessed_at: str | None = None


class ProjectLink(BaseModel):
    id: str = Field(default_factory=lambda: new_id("plink"))
    project_id: str
    link_type: ProjectLinkType | str
    link_ref: str
    title: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utcnow_iso)

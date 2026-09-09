"""API request/response schemas (v1)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    message: str
    user_id: str = "default"


class AskResponse(BaseModel):
    reply: str
    session_hint: str | None = None


class StatusResponse(BaseModel):
    version: str
    state: str
    env: str
    modules: list[str]
    health_level: str | None = None
    health_message: str | None = None


class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    priority: float = 0.5
    domain: str | None = None
    activate: bool = False


class GoalCreate(BaseModel):
    title: str
    horizon: str = "medium"
    priority: float = 0.5
    project_id: str | None = None
    description: str = ""


class WorkflowStart(BaseModel):
    name: str
    task: str = ""
    context: dict[str, Any] = Field(default_factory=dict)


class ApprovalDecide(BaseModel):
    approve: bool = True
    decided_by: str = "api"


class AutomationRun(BaseModel):
    name: str
    context: dict[str, Any] = Field(default_factory=dict)


class MemoryStore(BaseModel):
    content: str
    importance: float = 0.7


class VariantProposalCreate(BaseModel):
    name: str
    payload: str
    parent_id: str | None = None
    mutation_description: str | None = None
    mutation_target: str = "system_prompt"


class VariantApplyRequest(BaseModel):
    approved: bool = True
    approver: str = "api"
    reason: str | None = None
    run_id: str
    mean_score: float
    baseline_mean_score: float
    cases_evaluated: int = 0
    cases_won: int = 0


class SoupComparisonRequest(BaseModel):
    name: str
    variant_ids: list[str]
    eval_set: list[dict[str, Any]] = Field(default_factory=list)
    eval_set_name: str = "builtin"


class OK(BaseModel):
    ok: bool = True
    detail: Any = None

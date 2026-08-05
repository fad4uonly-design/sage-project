"""Workflow engine models."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso


class StepType(str, Enum):
    SKILL = "skill"
    TOOL = "tool"
    AGENT = "agent"
    DECISION = "decision"
    CONDITION = "condition"
    PARALLEL = "parallel"
    LOOP = "loop"
    APPROVAL = "approval"
    SET = "set"
    MEMORY = "memory"
    NOTIFY = "notify"


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class RetryPolicy(BaseModel):
    max_attempts: int = 1
    delay_seconds: float = 0.0
    on: list[str] = Field(default_factory=lambda: ["error"])


class WorkflowStepDef(BaseModel):
    id: str
    type: StepType
    name: str = ""
    # type-specific config
    skill_id: str | None = None
    tool_name: str | None = None
    agent_domain: str | None = None
    # condition: expression over context (simple key truthiness / equality)
    when: str | None = None
    # For condition steps: next step if true / false
    if_true: str | None = None
    if_false: str | None = None
    # Parallel: child step ids
    steps: list[str] = Field(default_factory=list)
    # Loop
    over: str | None = None  # context key with list
    body: str | None = None  # step id to run per item
    # Generic params (templates may use {{context.key}})
    params: dict[str, Any] = Field(default_factory=dict)
    input_key: str | None = None  # where to put output in context
    timeout_seconds: float | None = None
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    on_error: str | None = None  # next step id or "fail" / "continue"
    next: str | None = None  # default next step


class WorkflowDefinition(BaseModel):
    id: str = Field(default_factory=lambda: new_id("wdef"))
    name: str
    version: str = "1.0.0"
    description: str = ""
    entry: str  # first step id
    steps: list[WorkflowStepDef] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    def step_map(self) -> dict[str, WorkflowStepDef]:
        return {s.id: s for s in self.steps}


class StepRunRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("wstep"))
    step_id: str
    status: str
    attempt: int = 1
    input: dict[str, Any] = Field(default_factory=dict)
    output: Any = None
    error: str | None = None
    started_at: str = Field(default_factory=utcnow_iso)
    completed_at: str | None = None


class WorkflowRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("wrun"))
    definition_id: str
    definition_name: str = ""
    status: WorkflowStatus = WorkflowStatus.PENDING
    context: dict[str, Any] = Field(default_factory=dict)
    current_step: str | None = None
    checkpoint: dict[str, Any] = Field(default_factory=dict)
    step_history: list[StepRunRecord] = Field(default_factory=list)
    result: Any = None
    error: str | None = None
    started_at: str = Field(default_factory=utcnow_iso)
    updated_at: str = Field(default_factory=utcnow_iso)
    completed_at: str | None = None
    principal: str = "core"
    parent_run_id: str | None = None

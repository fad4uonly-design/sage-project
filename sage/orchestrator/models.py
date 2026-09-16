"""Orchestrator domain models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso


class IntentKind(StrEnum):
    CHAT = "chat"
    REMEMBER = "remember"
    RECALL = "recall"
    KNOWLEDGE = "knowledge"
    PLAN = "plan"
    REASON = "reason"
    RESEARCH = "research"
    DOCUMENT = "document"
    AGENT = "agent"
    TOOL = "tool"
    STATUS = "status"
    LEARN = "learn"
    UNKNOWN = "unknown"


class Intent(BaseModel):
    kind: IntentKind
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    subject: str = ""
    raw_message: str = ""
    entities: dict[str, Any] = Field(default_factory=dict)
    hints: list[str] = Field(default_factory=list)


class PipelineStep(StrEnum):
    ANALYZE_INTENT = "analyze_intent"
    RECALL_MEMORY = "recall_memory"
    SEARCH_KNOWLEDGE = "search_knowledge"
    RETRIEVE = "retrieve"
    REASON = "reason"
    PLAN = "plan"
    DISPATCH_AGENT = "dispatch_agent"
    INVOKE_TOOL = "invoke_tool"
    STORE_MEMORY = "store_memory"
    LEARN = "learn"
    COMPOSE_RESPONSE = "compose_response"
    STATUS = "status"


class ExecutionPlan(BaseModel):
    id: str = Field(default_factory=lambda: new_id("xplan"))
    intent: Intent
    steps: list[PipelineStep] = Field(default_factory=list)
    created_at: str = Field(default_factory=utcnow_iso)


class StepResult(BaseModel):
    step: PipelineStep
    success: bool = True
    output: Any = None
    error: str | None = None
    duration_ms: float = 0.0


class OrchestratorResult(BaseModel):
    plan_id: str
    intent: Intent
    response: str
    steps: list[StepResult] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utcnow_iso)

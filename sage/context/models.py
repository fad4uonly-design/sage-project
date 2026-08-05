"""Context engine models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso


class ProactiveSuggestion(BaseModel):
    id: str = Field(default_factory=lambda: new_id("sugg"))
    title: str
    body: str
    category: str = "general"
    priority: float = Field(default=0.5, ge=0.0, le=1.0)
    status: str = "open"  # open | dismissed | acted
    related_project_id: str | None = None
    related_goal_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utcnow_iso)
    dismissed_at: str | None = None
    acted_at: str | None = None


class SessionContinuity(BaseModel):
    """What SAGE should restore on startup."""

    active_project_id: str | None = None
    active_goal_ids: list[str] = Field(default_factory=list)
    pending_approvals: list[dict[str, Any]] = Field(default_factory=list)
    running_automations: list[dict[str, Any]] = Field(default_factory=list)
    unfinished_workflows: list[dict[str, Any]] = Field(default_factory=list)
    recent_reasoning: list[str] = Field(default_factory=list)
    open_decisions: list[str] = Field(default_factory=list)
    last_conversation_summary: str | None = None
    priorities: list[str] = Field(default_factory=list)
    updated_at: str = Field(default_factory=utcnow_iso)


class UnifiedContext(BaseModel):
    """Fused view for the Orchestrator and agents."""

    generated_at: str = Field(default_factory=utcnow_iso)
    active_projects: list[dict[str, Any]] = Field(default_factory=list)
    goals: list[dict[str, Any]] = Field(default_factory=list)
    priorities: list[str] = Field(default_factory=list)
    open_tasks: list[dict[str, Any]] = Field(default_factory=list)
    recent_memories: list[str] = Field(default_factory=list)
    graph_highlights: list[str] = Field(default_factory=list)
    running_workflows: list[dict[str, Any]] = Field(default_factory=list)
    pending_approvals: list[dict[str, Any]] = Field(default_factory=list)
    recent_documents: list[str] = Field(default_factory=list)
    long_term_interests: list[str] = Field(default_factory=list)
    suggestions: list[dict[str, Any]] = Field(default_factory=list)
    session: SessionContinuity = Field(default_factory=SessionContinuity)
    environment: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""

    def as_orchestrator_context(self) -> dict[str, Any]:
        """Flatten into dict the Orchestrator / agents can consume."""
        return {
            "context_summary": self.summary,
            "active_projects": [p.get("name") for p in self.active_projects[:5]],
            "active_project_ids": [p.get("id") for p in self.active_projects[:5]],
            "goals": [g.get("title") for g in self.goals[:8]],
            "priorities": list(self.priorities[:8]),
            "open_tasks": self.open_tasks[:10],
            "memories": list(self.recent_memories[:8]),
            "graph_facts": list(self.graph_highlights[:8]),
            "documents": list(self.recent_documents[:5]),
            "long_term_interests": list(self.long_term_interests[:8]),
            "suggestions": [s.get("title") for s in self.suggestions[:5]],
            "pending_approvals_count": len(self.pending_approvals),
            "running_workflows_count": len(self.running_workflows),
            "environment": dict(self.environment),
            "unified_context": True,
        }


class ContextSnapshot(BaseModel):
    id: str = Field(default_factory=lambda: new_id("csnap"))
    kind: str = "session"
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utcnow_iso)

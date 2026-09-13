"""
Workflow Library — reusable multi-step procedures agents can run.

Workflows are action-oriented recipes (diagnose disease, build budget, SWOT, …)
rather than free-form chat.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from sage.logging import get_logger
from sage.utils.time import utcnow_iso

log = get_logger(__name__)

# Handler: (context, params) -> step output dict/str
StepHandler = Callable[[dict[str, Any], dict[str, Any]], Awaitable[Any] | Any]


class WorkflowStep(BaseModel):
    id: str
    title: str
    description: str = ""
    optional: bool = False


class WorkflowResult(BaseModel):
    workflow_id: str
    workflow_name: str
    success: bool
    steps: list[dict[str, Any]] = Field(default_factory=list)
    output: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    created_at: str = Field(default_factory=utcnow_iso)


@dataclass
class Workflow:
    id: str
    name: str
    domain: str
    description: str
    steps: list[WorkflowStep]
    handler: StepHandler  # runs full workflow given context + params
    triggers: list[str] = field(default_factory=list)  # keywords
    version: str = "1.0.0"

    def match_score(self, text: str) -> float:
        lower = text.lower()
        hits = sum(1 for t in self.triggers if t in lower)
        if self.name.lower() in lower:
            hits += 2
        if not self.triggers:
            return 0.0
        return min(1.0, hits / max(len(self.triggers), 1) * 1.5)


class WorkflowLibrary:
    """Registry of workflows, optionally scoped by domain."""

    def __init__(self) -> None:
        self._workflows: dict[str, Workflow] = {}

    def register(self, workflow: Workflow) -> None:
        self._workflows[workflow.id] = workflow
        log.debug(
            "workflow.registered",
            id=workflow.id,
            domain=workflow.domain,
            name=workflow.name,
        )

    def get(self, workflow_id: str) -> Workflow | None:
        return self._workflows.get(workflow_id)

    def list_workflows(self, *, domain: str | None = None) -> list[Workflow]:
        items = list(self._workflows.values())
        if domain:
            items = [w for w in items if w.domain == domain or w.domain == "shared"]
        return items

    def match(self, text: str, *, domain: str | None = None, limit: int = 3) -> list[tuple[Workflow, float]]:
        scored: list[tuple[Workflow, float]] = []
        for w in self.list_workflows(domain=domain):
            score = w.match_score(text)
            if score > 0:
                scored.append((w, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    async def run(
        self,
        workflow_id: str,
        context: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> WorkflowResult:
        wf = self._workflows.get(workflow_id)
        if wf is None:
            return WorkflowResult(
                workflow_id=workflow_id,
                workflow_name="unknown",
                success=False,
                error=f"Unknown workflow: {workflow_id}",
            )
        params = params or {}
        try:
            import inspect

            result = wf.handler(context, params)
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, WorkflowResult):
                return result
            if isinstance(result, dict):
                return WorkflowResult(
                    workflow_id=wf.id,
                    workflow_name=wf.name,
                    success=bool(result.get("success", True)),
                    steps=list(result.get("steps") or []),
                    output=str(result.get("output") or ""),
                    data=dict(result.get("data") or {}),
                    error=result.get("error"),
                )
            return WorkflowResult(
                workflow_id=wf.id,
                workflow_name=wf.name,
                success=True,
                output=str(result),
            )
        except Exception as exc:
            log.exception("workflow.failed", id=wf.id)
            return WorkflowResult(
                workflow_id=wf.id,
                workflow_name=wf.name,
                success=False,
                error=str(exc),
            )


def new_workflow_id(domain: str, slug: str) -> str:
    return f"wf_{domain}_{slug}"

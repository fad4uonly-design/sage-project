"""Agent protocols."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso


class AgentTask(BaseModel):
    id: str = Field(default_factory=lambda: new_id("task"))
    description: str
    domain: str | None = None
    priority: float = 0.5
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utcnow_iso)


class AgentResult(BaseModel):
    task_id: str
    agent_id: str
    success: bool
    output: str
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


@runtime_checkable
class Agent(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def domain(self) -> str: ...

    @property
    def capabilities(self) -> frozenset[str]: ...

    async def can_handle(self, task: AgentTask) -> float: ...

    async def execute(self, task: AgentTask) -> AgentResult: ...


@runtime_checkable
class AgentOrchestrator(Protocol):
    async def dispatch(self, task: AgentTask) -> AgentResult: ...

    async def collaborate(self, task: AgentTask, agent_ids: Sequence[str]) -> AgentResult: ...

    def list_agents(self) -> list[dict[str, Any]]: ...

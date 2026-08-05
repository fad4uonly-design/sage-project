"""Base agent helpers."""

from __future__ import annotations

from sage.agents.interfaces import AgentResult, AgentTask
from sage.utils.ids import new_id


class BaseAgent:
    domain: str = "general"
    capabilities: frozenset[str] = frozenset()

    def __init__(self, agent_id: str | None = None) -> None:
        self._id = agent_id or new_id("agent")

    @property
    def id(self) -> str:
        return self._id

    async def can_handle(self, task: AgentTask) -> float:
        if task.domain and task.domain == self.domain:
            return 0.9
        desc = task.description.lower()
        hits = sum(1 for c in self.capabilities if c in desc)
        if hits:
            return min(0.85, 0.3 + hits * 0.2)
        return 0.1

    async def execute(self, task: AgentTask) -> AgentResult:
        raise NotImplementedError

"""Agent module."""

from __future__ import annotations

from sage.config.settings import Settings
from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.events.bus import EventBus
from sage.agents.builtin import (
    DocumentAgent,
    GeneralAssistantAgent,
    PlanningAgent,
    ResearchAgent,
)
from sage.agents.interfaces import AgentOrchestrator
from sage.agents.orchestrator import DefaultAgentOrchestrator


class AgentModule(BaseModule):
    name = "agents"
    version = "0.1.0"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._orch: DefaultAgentOrchestrator | None = None

    async def _on_initialize(self) -> None:
        settings = self.container.resolve(Settings)
        events = self.container.try_resolve(EventBus)  # type: ignore[type-abstract]
        self._orch = DefaultAgentOrchestrator(events, container=self.container)
        if settings.agents.enabled:
            for agent in (
                GeneralAssistantAgent(self.container),
                ResearchAgent(self.container),
                PlanningAgent(self.container),
                DocumentAgent(self.container),
            ):
                self._orch.register(agent)
        self.container.register_instance(AgentOrchestrator, self._orch)  # type: ignore[type-abstract]
        self.container.register_instance(DefaultAgentOrchestrator, self._orch)

    async def _on_health(self) -> HealthStatus | None:
        if self._orch is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        agents = self._orch.list_agents()
        return HealthStatus.healthy(self.name, "ok", agents=len(agents))

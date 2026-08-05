"""Agent module — core + domain specialists."""

from __future__ import annotations

from sage.agents.builtin import (
    DocumentAgent,
    GeneralAssistantAgent,
    PlanningAgent,
    ResearchAgent,
)
from sage.agents.domain import (
    AgricultureAgent,
    BusinessAgent,
    FinanceAgent,
    ProgrammingAgent,
)
from sage.agents.interfaces import AgentOrchestrator
from sage.agents.orchestrator import DefaultAgentOrchestrator
from sage.agents.workflows.library import WorkflowLibrary
from sage.config.settings import Settings
from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.events.bus import EventBus


class AgentModule(BaseModule):
    name = "agents"
    version = "0.3.0"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._orch: DefaultAgentOrchestrator | None = None

    async def _on_initialize(self) -> None:
        settings = self.container.resolve(Settings)
        events = self.container.try_resolve(EventBus)  # type: ignore[type-abstract]
        self._orch = DefaultAgentOrchestrator(events, container=self.container)

        # Shared workflow library view (union of domain libraries after agent init)
        shared_lib = WorkflowLibrary()
        self.container.register_instance(WorkflowLibrary, shared_lib)

        if settings.agents.enabled:
            core_agents = [
                GeneralAssistantAgent(self.container),
                ResearchAgent(self.container),
                PlanningAgent(self.container),
                DocumentAgent(self.container),
            ]
            domain_agents = [
                AgricultureAgent(self.container),
                FinanceAgent(self.container),
                BusinessAgent(self.container),
                ProgrammingAgent(self.container),
            ]
            for agent in (*core_agents, *domain_agents):
                self._orch.register(agent)
                # Merge domain workflows into shared library
                if hasattr(agent, "workflows"):
                    for wf in agent.workflows.list_workflows():
                        shared_lib.register(wf)

        self.container.register_instance(AgentOrchestrator, self._orch)  # type: ignore[type-abstract]
        self.container.register_instance(DefaultAgentOrchestrator, self._orch)

    async def _on_health(self) -> HealthStatus | None:
        if self._orch is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        agents = self._orch.list_agents()
        domains = sorted({a["domain"] for a in agents})
        return HealthStatus.healthy(
            self.name,
            "ok",
            agents=len(agents),
            domains=domains,
        )

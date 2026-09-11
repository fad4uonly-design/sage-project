"""Agent module — core + domain specialists + Business Intelligence Suite."""

from __future__ import annotations

from typing import cast

from sage.agents.builtin import (
    DocumentAgent,
    GeneralAssistantAgent,
    PlanningAgent,
    ResearchAgent,
)
from sage.agents.domain import (
    AgricultureAgent,
    FinanceAgent,
    ProgrammingAgent,
    create_business_advisors,
)
from sage.agents.interfaces import Agent, AgentOrchestrator
from sage.agents.orchestrator import DefaultAgentOrchestrator
from sage.agents.workflows.library import WorkflowLibrary
from sage.config.settings import Settings
from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.events.bus import EventBus
from sage.logging import get_logger

log = get_logger(__name__)


class AgentModule(BaseModule):
    name = "agents"
    version = "0.3.1"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._orch: DefaultAgentOrchestrator | None = None

    async def _on_initialize(self) -> None:
        settings = self.container.resolve(Settings)
        events = self.container.try_resolve(EventBus)
        self._orch = DefaultAgentOrchestrator(events, container=self.container)

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
                ProgrammingAgent(self.container),
            ]
            # Business Intelligence Suite (12 advisors) — replaces single BusinessAgent
            bi_advisors = create_business_advisors(self.container)
            log.info("agents.bi_suite_loaded", count=len(bi_advisors))

            for agent in (*core_agents, *domain_agents, *bi_advisors):
                self._orch.register(cast(Agent, agent))
                if hasattr(agent, "workflows"):
                    for wf in agent.workflows.list_workflows():
                        shared_lib.register(wf)

        self.container.register_instance(AgentOrchestrator, self._orch)
        self.container.register_instance(DefaultAgentOrchestrator, self._orch)

    async def _on_health(self) -> HealthStatus | None:
        if self._orch is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        agents = self._orch.list_agents()
        domains = sorted({a["domain"] for a in agents})
        bi_domains = {
            "business",
            "marketing",
            "sales",
            "operations",
            "financial_planning",
            "accounting",
            "hr",
            "project_management",
            "market_research",
            "analytics",
            "risk_compliance",
            "strategy",
        }
        bi_count = sum(1 for d in domains if d in bi_domains)
        return HealthStatus.healthy(
            self.name,
            "ok",
            agents=len(agents),
            domains=domains,
            bi_advisors=bi_count,
        )

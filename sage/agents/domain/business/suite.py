"""Business Intelligence Suite factory and legacy compatibility."""

from __future__ import annotations

from typing import Any

from sage.agents.domain.business.advisors import (
    ALL_BI_ADVISOR_CLASSES,
    BusinessAdvisorAgent,
)
from sage.agents.domain_base import DomainAgent
from sage.logging import get_logger

log = get_logger(__name__)


class BusinessIntelligenceSuite:
    """
    Groups all BI advisors for registration and discovery.

    Backward compatible: `legacy_business_agent` returns the hub Business Advisor
    which covers the old single BusinessAgent surface area.
    """

    def __init__(self, advisors: list[DomainAgent]) -> None:
        self.advisors = advisors

    @property
    def domains(self) -> list[str]:
        return [a.domain for a in self.advisors]

    def workflow_count(self) -> int:
        return sum(len(a.workflows.list_workflows()) for a in self.advisors)


def create_business_advisors(container: Any) -> list[DomainAgent]:
    """Instantiate all BI suite advisors bound to the DI container."""
    advisors: list[DomainAgent] = []
    for cls in ALL_BI_ADVISOR_CLASSES:
        agent = cls(container)
        advisors.append(agent)
        log.info(
            "bi.advisor_created",
            principal=agent.profile.principal,
            domain=agent.domain,
            workflows=len(agent.workflows.list_workflows()),
        )
    return advisors


def legacy_business_agent(container: Any) -> DomainAgent:
    """
    Compatibility helper — the primary business hub advisor.

    Existing code that expected a single BusinessAgent can use this.
    """
    return BusinessAdvisorAgent(container)

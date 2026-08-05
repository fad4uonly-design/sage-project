"""
Business Intelligence Suite (v0.3.1).

Backward compatible:
    from sage.agents.domain.business import BusinessAgent
    from sage.agents.domain import BusinessAgent
"""

from __future__ import annotations

from sage.agents.domain.business.advisors import (
    ALL_BI_ADVISOR_CLASSES,
    AccountingAdvisor,
    BusinessAdvisorAgent,
    BusinessAnalyticsAdvisor,
    FinancialPlanningAdvisor,
    HRAdvisor,
    MarketResearchAdvisor,
    MarketingAdvisor,
    OperationsAdvisor,
    ProjectManagementAdvisor,
    RiskComplianceAdvisor,
    SalesAdvisor,
    StrategyAdvisor,
)
from sage.agents.domain.business.suite import (
    BusinessIntelligenceSuite,
    create_business_advisors,
    legacy_business_agent,
)

# Historical name used throughout v0.3.0
BusinessAgent = BusinessAdvisorAgent

__all__ = [
    "ALL_BI_ADVISOR_CLASSES",
    "AccountingAdvisor",
    "BusinessAdvisorAgent",
    "BusinessAgent",
    "BusinessAnalyticsAdvisor",
    "BusinessIntelligenceSuite",
    "FinancialPlanningAdvisor",
    "HRAdvisor",
    "MarketResearchAdvisor",
    "MarketingAdvisor",
    "OperationsAdvisor",
    "ProjectManagementAdvisor",
    "RiskComplianceAdvisor",
    "SalesAdvisor",
    "StrategyAdvisor",
    "create_business_advisors",
    "legacy_business_agent",
]

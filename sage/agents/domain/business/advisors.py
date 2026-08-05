"""Business Intelligence advisors — specialized DomainAgent subclasses."""

from __future__ import annotations

from sage.agents.domain.business.base import BusinessAdvisor, bi_profile
from sage.agents.domain.business.workflows import register_all_bi_workflows


class BusinessAdvisorAgent(BusinessAdvisor):
    """General business advisory + planning hub."""

    profile = bi_profile(
        principal="business_advisor",
        domain="business",
        display_name="Business Advisor",
        description="Business planning, models, feasibility, general advisory hub",
        capabilities=[
            "business",
            "business plan",
            "startup",
            "expansion",
            "feasibility",
            "business model",
            "advisory",
            "venture",
        ],
        workflows=[
            "create_plan",
            "startup_planning",
            "expansion_planning",
            "business_model",
            "feasibility",
            "swot",
            "decision_support",
        ],
        reasoning_strategies=["business", "planning", "decision", "risk"],
    )

    def register_workflows(self) -> None:
        register_all_bi_workflows(
            self.workflows,
            self,
            domain=self.domain,
            workflow_ids=list(self.profile.workflows),
        )


class MarketingAdvisor(BusinessAdvisor):
    profile = bi_profile(
        principal="marketing_advisor",
        domain="marketing",
        display_name="Marketing Advisor",
        description="Marketing plans, segmentation, campaigns, branding, positioning",
        capabilities=[
            "marketing",
            "campaign",
            "branding",
            "brand",
            "segmentation",
            "positioning",
            "promotion",
            "content",
            "advertising",
        ],
        workflows=[
            "marketing_plan",
            "segmentation",
            "campaign",
            "branding",
            "positioning",
        ],
        reasoning_strategies=["business", "decision", "planning"],
    )

    def register_workflows(self) -> None:
        register_all_bi_workflows(
            self.workflows, self, domain=self.domain, workflow_ids=list(self.profile.workflows)
        )


class SalesAdvisor(BusinessAdvisor):
    profile = bi_profile(
        principal="sales_advisor",
        domain="sales",
        display_name="Sales Advisor",
        description="Sales forecast, pricing, pipeline, customer growth",
        capabilities=[
            "sales",
            "pipeline",
            "forecast",
            "pricing",
            "leads",
            "quota",
            "customer growth",
            "deal",
        ],
        workflows=["sales_forecast", "pricing", "pipeline", "customer_growth"],
        reasoning_strategies=["business", "decision", "mathematical"],
    )

    def register_workflows(self) -> None:
        register_all_bi_workflows(
            self.workflows, self, domain=self.domain, workflow_ids=list(self.profile.workflows)
        )


class OperationsAdvisor(BusinessAdvisor):
    profile = bi_profile(
        principal="operations_advisor",
        domain="operations",
        display_name="Operations Advisor",
        description="Process optimization, inventory, procurement, resource allocation",
        capabilities=[
            "operations",
            "process",
            "inventory",
            "procurement",
            "supply",
            "logistics",
            "capacity",
            "resource allocation",
        ],
        workflows=["process", "inventory", "procurement", "resources"],
        reasoning_strategies=["planning", "business", "risk"],
    )

    def register_workflows(self) -> None:
        register_all_bi_workflows(
            self.workflows, self, domain=self.domain, workflow_ids=list(self.profile.workflows)
        )


class FinancialPlanningAdvisor(BusinessAdvisor):
    """BI-side financial planning (complements FinanceAgent domain=finance)."""

    profile = bi_profile(
        principal="financial_planning_advisor",
        domain="financial_planning",
        display_name="Financial Planning Advisor",
        description="Budgets, cash flow, profitability, investment framing for business",
        capabilities=[
            "financial planning",
            "budget",
            "cash flow",
            "cashflow",
            "profitability",
            "investment",
            "loan",
            "capital",
        ],
        workflows=["budget", "cashflow", "profitability", "loan_comparison", "investment"],
        reasoning_strategies=["business", "mathematical", "risk", "decision"],
        tools=["calculator"],
        collaborate_with=["finance", "accounting", "strategy", "operations"],
    )

    def register_workflows(self) -> None:
        register_all_bi_workflows(
            self.workflows, self, domain=self.domain, workflow_ids=list(self.profile.workflows)
        )


class AccountingAdvisor(BusinessAdvisor):
    profile = bi_profile(
        principal="accounting_advisor",
        domain="accounting",
        display_name="Accounting Advisor",
        description="Journal entries, statements, ratios, break-even, cost analysis",
        capabilities=[
            "accounting",
            "journal",
            "ledger",
            "financial statements",
            "ratio",
            "break-even",
            "breakeven",
            "cost analysis",
            "bookkeeping",
        ],
        workflows=["journal", "statements", "ratios", "breakeven", "cost_analysis"],
        reasoning_strategies=["mathematical", "business", "logical"],
        tools=["calculator"],
        collaborate_with=["finance", "financial_planning", "operations"],
    )

    def register_workflows(self) -> None:
        register_all_bi_workflows(
            self.workflows, self, domain=self.domain, workflow_ids=list(self.profile.workflows)
        )


class HRAdvisor(BusinessAdvisor):
    profile = bi_profile(
        principal="hr_advisor",
        domain="hr",
        display_name="HR Advisor",
        description="Org design, hiring plans, performance, HR compliance hooks",
        capabilities=[
            "hr",
            "hiring",
            "headcount",
            "org design",
            "people",
            "talent",
            "onboarding",
            "performance",
        ],
        workflows=["hr_planning", "resources"],
        reasoning_strategies=["planning", "business", "ethical"],
        collaborate_with=["operations", "finance", "risk_compliance", "project_management"],
    )

    def register_workflows(self) -> None:
        register_all_bi_workflows(
            self.workflows, self, domain=self.domain, workflow_ids=list(self.profile.workflows)
        )


class ProjectManagementAdvisor(BusinessAdvisor):
    profile = bi_profile(
        principal="project_management_advisor",
        domain="project_management",
        display_name="Project Management Advisor",
        description="Project plans, schedules, risks, milestones, resources",
        capabilities=[
            "project",
            "project management",
            "milestone",
            "schedule",
            "gantt",
            "raid",
            "wbs",
            "delivery",
        ],
        workflows=["project_plan", "scheduling", "risk_tracking", "milestones", "resources"],
        reasoning_strategies=["planning", "risk", "decision"],
        collaborate_with=["operations", "finance", "programming", "hr"],
    )

    def register_workflows(self) -> None:
        register_all_bi_workflows(
            self.workflows, self, domain=self.domain, workflow_ids=list(self.profile.workflows)
        )


class MarketResearchAdvisor(BusinessAdvisor):
    profile = bi_profile(
        principal="market_research_advisor",
        domain="market_research",
        display_name="Market Research Advisor",
        description="Market and customer research briefs and methods",
        capabilities=[
            "market research",
            "research",
            "competitor research",
            "customer research",
            "survey",
            "interview",
            "tam",
            "sam",
        ],
        workflows=["market_research", "segmentation", "positioning", "trend"],
        reasoning_strategies=["scientific", "business", "induction"],
        collaborate_with=["marketing", "strategy", "sales", "analytics"],
    )

    def register_workflows(self) -> None:
        register_all_bi_workflows(
            self.workflows, self, domain=self.domain, workflow_ids=list(self.profile.workflows)
        )


class BusinessAnalyticsAdvisor(BusinessAdvisor):
    profile = bi_profile(
        principal="business_analytics_advisor",
        domain="analytics",
        display_name="Business Analytics Advisor",
        description="KPIs, trends, performance reports, forecasting",
        capabilities=[
            "analytics",
            "kpi",
            "dashboard",
            "metrics",
            "trend",
            "forecast",
            "performance report",
            "reporting",
        ],
        workflows=["kpi_dashboard", "trend", "performance_report", "forecasting"],
        reasoning_strategies=["mathematical", "business", "induction"],
        tools=["calculator"],
        collaborate_with=["finance", "sales", "operations", "strategy", "programming"],
    )

    def register_workflows(self) -> None:
        register_all_bi_workflows(
            self.workflows, self, domain=self.domain, workflow_ids=list(self.profile.workflows)
        )


class RiskComplianceAdvisor(BusinessAdvisor):
    profile = bi_profile(
        principal="risk_compliance_advisor",
        domain="risk_compliance",
        display_name="Risk & Compliance Advisor",
        description="SWOT, risk assessment, compliance, decision support",
        capabilities=[
            "risk",
            "compliance",
            "swot",
            "regulatory",
            "threat",
            "mitigation",
            "decision support",
            "governance",
        ],
        workflows=["swot", "risk_assessment", "compliance", "decision_support", "risk_tracking"],
        reasoning_strategies=["risk", "ethical", "decision", "business"],
        collaborate_with=["finance", "operations", "hr", "strategy", "legal"],
    )

    def register_workflows(self) -> None:
        register_all_bi_workflows(
            self.workflows, self, domain=self.domain, workflow_ids=list(self.profile.workflows)
        )


class StrategyAdvisor(BusinessAdvisor):
    profile = bi_profile(
        principal="strategy_advisor",
        domain="strategy",
        display_name="Strategy Advisor",
        description="Strategic direction, SWOT, competitive options",
        capabilities=[
            "strategy",
            "strategic",
            "competitive",
            "corporate strategy",
            "direction",
            "vision",
            "moat",
        ],
        workflows=["strategy_direction", "swot", "business_model", "feasibility", "decision_support"],
        reasoning_strategies=["business", "decision", "risk", "planning"],
        collaborate_with=[
            "finance",
            "market_research",
            "marketing",
            "operations",
            "risk_compliance",
            "analytics",
        ],
    )

    def register_workflows(self) -> None:
        register_all_bi_workflows(
            self.workflows, self, domain=self.domain, workflow_ids=list(self.profile.workflows)
        )


ALL_BI_ADVISOR_CLASSES: list[type[BusinessAdvisor]] = [
    BusinessAdvisorAgent,
    MarketingAdvisor,
    SalesAdvisor,
    OperationsAdvisor,
    FinancialPlanningAdvisor,
    AccountingAdvisor,
    HRAdvisor,
    ProjectManagementAdvisor,
    MarketResearchAdvisor,
    BusinessAnalyticsAdvisor,
    RiskComplianceAdvisor,
    StrategyAdvisor,
]

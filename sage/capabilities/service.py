"""Capabilities module — registers built-in agent capabilities on boot."""

from __future__ import annotations

from sage.capabilities.interfaces import CapabilityRegistry
from sage.capabilities.models import CapabilityDescriptor
from sage.capabilities.registry import SQLiteCapabilityRegistry
from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.db.connection import Database

# Core + agriculture + finance + programming + full BI suite (v0.3.1)
_BUILTIN: list[CapabilityDescriptor] = [
    CapabilityDescriptor(
        principal="general_assistant",
        principal_type="agent",
        domain="general",
        capabilities=["help", "assist", "explain", "chat"],
        tools=["echo", "current_time", "calculator"],
        permissions=["memory.read", "tools.invoke"],
        reasoning_strategies=["multi_step", "logical", "decision"],
        confidence_threshold=0.2,
    ),
    CapabilityDescriptor(
        principal="research_agent",
        principal_type="agent",
        domain="research",
        capabilities=["research", "investigate", "search", "lookup"],
        tools=[],
        permissions=["memory.read", "filesystem.read"],
        reasoning_strategies=["scientific", "logical", "induction"],
        confidence_threshold=0.35,
    ),
    CapabilityDescriptor(
        principal="planning_agent",
        principal_type="agent",
        domain="planning",
        capabilities=["plan", "schedule", "roadmap", "organize"],
        tools=[],
        permissions=["memory.read", "memory.write", "agents.dispatch"],
        reasoning_strategies=["planning", "decision", "risk"],
        confidence_threshold=0.35,
    ),
    CapabilityDescriptor(
        principal="document_agent",
        principal_type="agent",
        domain="documents",
        capabilities=["document", "summarize", "ingest", "analyze"],
        tools=[],
        permissions=["filesystem.read", "memory.write"],
        reasoning_strategies=["logical", "scientific"],
        confidence_threshold=0.35,
    ),
    CapabilityDescriptor(
        principal="agriculture_agent",
        principal_type="agent",
        domain="agriculture",
        capabilities=[
            "crop",
            "irrigation",
            "soil",
            "harvest",
            "greenhouse",
            "farm",
            "fertilizer",
            "pest",
            "disease",
            "blight",
        ],
        tools=["calculator", "current_time"],
        permissions=["memory.read", "memory.write"],
        reasoning_strategies=["agriculture", "scientific", "risk", "planning"],
        confidence_threshold=0.3,
        metadata={"status": "active", "suite": None},
    ),
    CapabilityDescriptor(
        principal="finance_agent",
        principal_type="agent",
        domain="finance",
        capabilities=[
            "budget",
            "invoice",
            "revenue",
            "profit",
            "cashflow",
            "loan",
            "investment",
            "cost",
            "expense",
        ],
        tools=["calculator"],
        permissions=["memory.read", "memory.write"],
        reasoning_strategies=["business", "mathematical", "risk", "decision"],
        confidence_threshold=0.3,
        metadata={"status": "active"},
    ),
    CapabilityDescriptor(
        principal="programming_agent",
        principal_type="agent",
        domain="programming",
        capabilities=[
            "code",
            "debug",
            "api",
            "python",
            "refactor",
            "test",
            "git",
            "plugin",
            "architecture",
        ],
        tools=[],
        permissions=["filesystem.read", "memory.read", "memory.write"],
        reasoning_strategies=["logical", "mathematical", "multi_step"],
        confidence_threshold=0.3,
        metadata={"status": "active"},
    ),
    # --- Business Intelligence Suite (v0.3.1) ---
    # Keep principal business_agent alias for backward-compatible capability lookups
    CapabilityDescriptor(
        principal="business_agent",
        principal_type="agent",
        domain="business",
        capabilities=[
            "business",
            "business plan",
            "startup",
            "expansion",
            "feasibility",
            "business model",
            "strategy",
            "swot",
        ],
        tools=["calculator", "current_time"],
        permissions=["memory.read", "memory.write"],
        reasoning_strategies=["business", "decision", "planning", "risk"],
        confidence_threshold=0.3,
        metadata={
            "status": "active",
            "suite": "business_intelligence",
            "role": "hub",
            "alias_of": "business_advisor",
            "workflows": [
                "create_plan",
                "startup_planning",
                "expansion_planning",
                "business_model",
                "feasibility",
                "swot",
                "decision_support",
            ],
        },
    ),
    CapabilityDescriptor(
        principal="business_advisor",
        principal_type="agent",
        domain="business",
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
        tools=["calculator", "current_time"],
        permissions=["memory.read", "memory.write"],
        reasoning_strategies=["business", "planning", "decision", "risk"],
        confidence_threshold=0.3,
        metadata={"status": "active", "suite": "business_intelligence"},
    ),
    CapabilityDescriptor(
        principal="marketing_advisor",
        principal_type="agent",
        domain="marketing",
        capabilities=[
            "marketing",
            "campaign",
            "branding",
            "brand",
            "segmentation",
            "positioning",
            "promotion",
            "advertising",
        ],
        tools=["calculator"],
        permissions=["memory.read", "memory.write"],
        reasoning_strategies=["business", "decision", "planning"],
        confidence_threshold=0.3,
        metadata={"status": "active", "suite": "business_intelligence"},
    ),
    CapabilityDescriptor(
        principal="sales_advisor",
        principal_type="agent",
        domain="sales",
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
        tools=["calculator"],
        permissions=["memory.read", "memory.write"],
        reasoning_strategies=["business", "decision", "mathematical"],
        confidence_threshold=0.3,
        metadata={"status": "active", "suite": "business_intelligence"},
    ),
    CapabilityDescriptor(
        principal="operations_advisor",
        principal_type="agent",
        domain="operations",
        capabilities=[
            "operations",
            "process",
            "inventory",
            "procurement",
            "supply",
            "logistics",
            "capacity",
        ],
        tools=["calculator"],
        permissions=["memory.read", "memory.write"],
        reasoning_strategies=["planning", "business", "risk"],
        confidence_threshold=0.3,
        metadata={"status": "active", "suite": "business_intelligence"},
    ),
    CapabilityDescriptor(
        principal="financial_planning_advisor",
        principal_type="agent",
        domain="financial_planning",
        capabilities=[
            "financial planning",
            "budget",
            "cash flow",
            "profitability",
            "investment",
            "capital",
        ],
        tools=["calculator"],
        permissions=["memory.read", "memory.write"],
        reasoning_strategies=["business", "mathematical", "risk", "decision"],
        confidence_threshold=0.3,
        metadata={"status": "active", "suite": "business_intelligence"},
    ),
    CapabilityDescriptor(
        principal="accounting_advisor",
        principal_type="agent",
        domain="accounting",
        capabilities=[
            "accounting",
            "journal",
            "ledger",
            "financial statements",
            "ratio",
            "break-even",
            "cost analysis",
            "bookkeeping",
        ],
        tools=["calculator"],
        permissions=["memory.read", "memory.write"],
        reasoning_strategies=["mathematical", "business", "logical"],
        confidence_threshold=0.3,
        metadata={"status": "active", "suite": "business_intelligence"},
    ),
    CapabilityDescriptor(
        principal="hr_advisor",
        principal_type="agent",
        domain="hr",
        capabilities=["hr", "hiring", "headcount", "org design", "talent", "onboarding"],
        tools=[],
        permissions=["memory.read", "memory.write"],
        reasoning_strategies=["planning", "business", "ethical"],
        confidence_threshold=0.3,
        metadata={"status": "active", "suite": "business_intelligence"},
    ),
    CapabilityDescriptor(
        principal="project_management_advisor",
        principal_type="agent",
        domain="project_management",
        capabilities=[
            "project",
            "project management",
            "milestone",
            "schedule",
            "gantt",
            "raid",
            "wbs",
        ],
        tools=[],
        permissions=["memory.read", "memory.write"],
        reasoning_strategies=["planning", "risk", "decision"],
        confidence_threshold=0.3,
        metadata={"status": "active", "suite": "business_intelligence"},
    ),
    CapabilityDescriptor(
        principal="market_research_advisor",
        principal_type="agent",
        domain="market_research",
        capabilities=[
            "market research",
            "competitor research",
            "customer research",
            "survey",
            "tam",
        ],
        tools=[],
        permissions=["memory.read", "memory.write"],
        reasoning_strategies=["scientific", "business", "induction"],
        confidence_threshold=0.3,
        metadata={"status": "active", "suite": "business_intelligence"},
    ),
    CapabilityDescriptor(
        principal="business_analytics_advisor",
        principal_type="agent",
        domain="analytics",
        capabilities=[
            "analytics",
            "kpi",
            "dashboard",
            "metrics",
            "trend",
            "forecast",
            "performance report",
        ],
        tools=["calculator"],
        permissions=["memory.read", "memory.write"],
        reasoning_strategies=["mathematical", "business", "induction"],
        confidence_threshold=0.3,
        metadata={"status": "active", "suite": "business_intelligence"},
    ),
    CapabilityDescriptor(
        principal="risk_compliance_advisor",
        principal_type="agent",
        domain="risk_compliance",
        capabilities=[
            "risk",
            "compliance",
            "swot",
            "regulatory",
            "governance",
            "decision support",
        ],
        tools=[],
        permissions=["memory.read", "memory.write"],
        reasoning_strategies=["risk", "ethical", "decision", "business"],
        confidence_threshold=0.3,
        metadata={"status": "active", "suite": "business_intelligence"},
    ),
    CapabilityDescriptor(
        principal="strategy_advisor",
        principal_type="agent",
        domain="strategy",
        capabilities=[
            "strategy",
            "strategic",
            "competitive",
            "corporate strategy",
            "direction",
            "vision",
        ],
        tools=[],
        permissions=["memory.read", "memory.write"],
        reasoning_strategies=["business", "decision", "risk", "planning"],
        confidence_threshold=0.3,
        metadata={"status": "active", "suite": "business_intelligence"},
    ),
]


class CapabilitiesModule(BaseModule):
    name = "capabilities"
    version = "0.3.1"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._reg: SQLiteCapabilityRegistry | None = None

    async def _on_initialize(self) -> None:
        db = self.container.resolve(Database)
        self._reg = SQLiteCapabilityRegistry(db)
        self.container.register_instance(CapabilityRegistry, self._reg)  # type: ignore[type-abstract]
        self.container.register_instance(SQLiteCapabilityRegistry, self._reg)
        for desc in _BUILTIN:
            await self._reg.register(desc)

    async def _on_health(self) -> HealthStatus | None:
        if self._reg is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        n = len(await self._reg.list_all())
        bi = sum(
            1
            for d in await self._reg.list_all()
            if (d.metadata or {}).get("suite") == "business_intelligence"
        )
        return HealthStatus.healthy(self.name, "ok", descriptors=n, bi_suite=bi)

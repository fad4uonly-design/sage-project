"""Capabilities module — registers built-in agent capabilities on boot."""

from __future__ import annotations

from sage.capabilities.interfaces import CapabilityRegistry
from sage.capabilities.models import CapabilityDescriptor
from sage.capabilities.registry import SQLiteCapabilityRegistry
from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.db.connection import Database


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
        metadata={
            "status": "active",
            "workflows": [
                "diagnose_disease",
                "irrigation_plan",
                "fertilizer",
                "crop_calendar",
                "compare_methods",
            ],
        },
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
            "accounting",
            "loan",
            "investment",
            "cost",
            "expense",
        ],
        tools=["calculator"],
        permissions=["memory.read", "memory.write"],
        reasoning_strategies=["business", "mathematical", "risk", "decision"],
        confidence_threshold=0.3,
        metadata={
            "status": "active",
            "workflows": [
                "loan_comparison",
                "budget",
                "investment",
                "cashflow",
                "expense_forecast",
            ],
        },
    ),
    CapabilityDescriptor(
        principal="business_agent",
        principal_type="agent",
        domain="business",
        capabilities=[
            "strategy",
            "market",
            "customer",
            "sales",
            "operations",
            "swot",
            "pricing",
            "kpi",
            "marketing",
        ],
        tools=[],
        permissions=["memory.read", "memory.write"],
        reasoning_strategies=["business", "decision", "planning", "risk"],
        confidence_threshold=0.3,
        metadata={
            "status": "active",
            "workflows": ["swot", "plan", "pricing", "kpi", "gtm"],
        },
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
        metadata={
            "status": "active",
            "workflows": [
                "scaffold",
                "debug",
                "refactor",
                "tests",
                "plugin",
                "review",
            ],
        },
    ),
]


class CapabilitiesModule(BaseModule):
    name = "capabilities"
    version = "0.3.0"
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
        return HealthStatus.healthy(self.name, "ok", descriptors=n)

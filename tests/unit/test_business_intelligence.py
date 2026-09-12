"""Business Intelligence Suite tests (v0.3.1)."""

from __future__ import annotations

import pytest
from sage.agents.domain.business import (
    BusinessAgent,
    MarketingAdvisor,
    create_business_advisors,
)
from sage.agents.interfaces import AgentOrchestrator, AgentTask
from sage.agents.workflows.library import WorkflowLibrary
from sage.capabilities.interfaces import CapabilityRegistry
from sage.core.engine import SageEngine
from sage.knowledge.graph.interfaces import KnowledgeGraph
from sage.knowledge.graph.models import EntityType, RelationType
from sage.orchestrator.interfaces import Orchestrator
from sage.orchestrator.models import IntentKind

BI_DOMAINS = {
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


@pytest.mark.asyncio
async def test_bi_advisors_registered(engine: SageEngine) -> None:
    orch = engine.container.resolve(AgentOrchestrator)  # type: ignore[type-abstract]
    domains = {a["domain"] for a in orch.list_agents()}
    missing = BI_DOMAINS - domains
    assert not missing, f"Missing BI domains: {missing}"


@pytest.mark.asyncio
async def test_business_agent_alias(engine: SageEngine) -> None:
    """Legacy BusinessAgent is the hub advisor."""
    assert BusinessAgent.profile.domain == "business"
    assert "business plan" in BusinessAgent.profile.capabilities or any(
        "plan" in c for c in BusinessAgent.profile.capabilities
    )


@pytest.mark.asyncio
async def test_create_business_advisors_count(engine: SageEngine) -> None:
    advisors = create_business_advisors(engine.container)
    assert len(advisors) == 12
    assert {a.domain for a in advisors} == BI_DOMAINS


@pytest.mark.asyncio
async def test_bi_workflows_in_shared_library(engine: SageEngine) -> None:
    lib = engine.container.resolve(WorkflowLibrary)
    all_wf = lib.list_workflows()
    # Agriculture (~5) + finance (~5) + programming (~6) + BI (many)
    assert len(all_wf) >= 40
    marketing = lib.list_workflows(domain="marketing")
    assert marketing
    accounting = lib.list_workflows(domain="accounting")
    assert any("breakeven" in w.id or "ratio" in w.id or "journal" in w.id for w in accounting)


@pytest.mark.asyncio
async def test_marketing_plan_workflow(engine: SageEngine) -> None:
    orch = engine.container.resolve(AgentOrchestrator)  # type: ignore[type-abstract]
    result = await orch.dispatch(
        AgentTask(description="Create a marketing plan for organic produce brand", domain="marketing")
    )
    assert result.success
    assert "marketing" in result.output.lower() or "audience" in result.output.lower()


@pytest.mark.asyncio
async def test_accounting_breakeven(engine: SageEngine) -> None:
    orch = engine.container.resolve(AgentOrchestrator)  # type: ignore[type-abstract]
    result = await orch.dispatch(
        AgentTask(
            description="Break-even analysis price 50 variable 20 fixed 10000",
            domain="accounting",
        )
    )
    assert result.success
    assert "break-even" in result.output.lower() or "break" in result.output.lower()
    # 10000 / (50-20) = 333.3...
    assert "333" in result.output


@pytest.mark.asyncio
async def test_swot_via_risk_or_business(engine: SageEngine) -> None:
    orch = engine.container.resolve(AgentOrchestrator)  # type: ignore[type-abstract]
    result = await orch.dispatch(
        AgentTask(description="SWOT analysis for a retail expansion", domain="risk_compliance")
    )
    assert result.success
    assert "strength" in result.output.lower()


@pytest.mark.asyncio
async def test_business_plan_hub(engine: SageEngine) -> None:
    orch = engine.container.resolve(AgentOrchestrator)  # type: ignore[type-abstract]
    result = await orch.dispatch(
        AgentTask(description="Create business plan for a farm shop startup", domain="business")
    )
    assert result.success
    low = result.output.lower()
    assert "business" in low or "plan" in low or "customer" in low


@pytest.mark.asyncio
async def test_kg_business_seed(engine: SageEngine) -> None:
    kg = engine.container.resolve(KnowledgeGraph)  # type: ignore[type-abstract]
    company = await kg.find_entity("Company")
    customer = await kg.find_entity("Customer")
    assert company is not None
    assert customer is not None
    stats = await kg.stats()
    assert stats["entities"] >= 15
    # Business relations from seed (sells_to / employs / etc.)
    sells = await kg.query_relation(subject="Company", relation=RelationType.SELLS_TO.value)
    employs = await kg.query_relation(subject="Company", relation=RelationType.EMPLOYS.value)
    competes = await kg.query_relation(relation=RelationType.COMPETES_WITH.value)
    assert sells or employs or competes or stats["edges"] >= 10



@pytest.mark.asyncio
async def test_kg_business_extraction(engine: SageEngine) -> None:
    kg = engine.container.resolve(KnowledgeGraph)  # type: ignore[type-abstract]
    result = await kg.extract_and_merge(
        "Acme Corp sells to Enterprise Customers. Acme Corp competes with Globex.",
        source="test_bi",
    )
    assert result.entities
    assert result.edges
    types = {e.entity_type for e in result.entities}
    # At least some business typing from lexicon/patterns
    assert types & {
        EntityType.COMPANY,
        EntityType.CUSTOMER,
        EntityType.COMPETITOR,
        EntityType.ORGANIZATION,
        EntityType.CONCEPT,
        EntityType.PERSON,
    }


@pytest.mark.asyncio
async def test_capability_registry_bi_suite(engine: SageEngine) -> None:
    reg = engine.container.resolve(CapabilityRegistry)  # type: ignore[type-abstract]
    all_caps = await reg.list_all()
    bi = [c for c in all_caps if (c.metadata or {}).get("suite") == "business_intelligence"]
    assert len(bi) >= 10
    # Legacy principal still present
    legacy = await reg.get("business_agent", "business")
    assert legacy is not None


@pytest.mark.asyncio
async def test_orchestrator_routes_marketing(engine: SageEngine) -> None:
    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]
    intent = await orch.analyze_intent("Build a marketing plan for Q4 campaign")
    assert intent.kind == IntentKind.AGENT
    assert intent.entities.get("domain") == "marketing"


@pytest.mark.asyncio
async def test_orchestrator_routes_accounting(engine: SageEngine) -> None:
    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]
    intent = await orch.analyze_intent("Run break-even analysis for new product")
    assert intent.kind == IntentKind.AGENT
    assert intent.entities.get("domain") == "accounting"


@pytest.mark.asyncio
async def test_ask_marketing_end_to_end(engine: SageEngine) -> None:
    reply = await engine.ask("Create a marketing plan for local bakery brand")
    assert reply
    assert any(k in reply.lower() for k in ("marketing", "audience", "channel", "brand", "campaign"))


@pytest.mark.asyncio
async def test_decision_engine_still_used_by_pricing(engine: SageEngine) -> None:
    orch = engine.container.resolve(AgentOrchestrator)  # type: ignore[type-abstract]
    result = await orch.dispatch(
        AgentTask(description="Pricing analysis for SaaS tiers", domain="sales")
    )
    assert result.success
    assert "decision" in result.output.lower() or "ranking" in result.output.lower() or "recommend" in result.output.lower()


@pytest.mark.asyncio
async def test_marketing_advisor_direct(engine: SageEngine) -> None:
    agent = MarketingAdvisor(engine.container)
    result = await agent.execute(
        AgentTask(description="Customer segmentation for B2B software", domain="marketing")
    )
    assert result.success
    assert "segment" in result.output.lower()

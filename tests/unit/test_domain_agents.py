"""Domain agent + workflow tests."""

from __future__ import annotations

import pytest

from sage.agents.interfaces import AgentOrchestrator, AgentTask
from sage.agents.workflows.library import WorkflowLibrary
from sage.core.engine import SageEngine


@pytest.mark.asyncio
async def test_agents_include_domains(engine: SageEngine) -> None:
    orch = engine.container.resolve(AgentOrchestrator)  # type: ignore[type-abstract]
    domains = {a["domain"] for a in orch.list_agents()}
    for d in ("agriculture", "finance", "business", "programming", "general", "planning"):
        assert d in domains


@pytest.mark.asyncio
async def test_agriculture_irrigation_workflow(engine: SageEngine) -> None:
    orch = engine.container.resolve(AgentOrchestrator)  # type: ignore[type-abstract]
    result = await orch.dispatch(
        AgentTask(
            description="Create an irrigation plan for tomatoes in summer heat",
            domain="agriculture",
        )
    )
    assert result.success
    assert "irrigation" in result.output.lower() or "water" in result.output.lower()
    assert result.data.get("domain") == "agriculture" or result.data.get("workflow")


@pytest.mark.asyncio
async def test_agriculture_disease_workflow(engine: SageEngine) -> None:
    orch = engine.container.resolve(AgentOrchestrator)  # type: ignore[type-abstract]
    result = await orch.dispatch(
        AgentTask(description="Diagnose blight disease on tomato plants", domain="agriculture")
    )
    assert result.success
    assert "blight" in result.output.lower() or "cause" in result.output.lower()


@pytest.mark.asyncio
async def test_finance_loan_workflow(engine: SageEngine) -> None:
    orch = engine.container.resolve(AgentOrchestrator)  # type: ignore[type-abstract]
    result = await orch.dispatch(
        AgentTask(
            description="Compare loans of 10000 at 8% and 12% for 5 years",
            domain="finance",
        )
    )
    assert result.success
    assert "loan" in result.output.lower()
    assert "%" in result.output or "interest" in result.output.lower()


@pytest.mark.asyncio
async def test_business_swot(engine: SageEngine) -> None:
    orch = engine.container.resolve(AgentOrchestrator)  # type: ignore[type-abstract]
    result = await orch.dispatch(
        AgentTask(description="SWOT analysis for a small organic farm", domain="business")
    )
    assert result.success
    assert "strength" in result.output.lower()


@pytest.mark.asyncio
async def test_programming_scaffold(engine: SageEngine) -> None:
    orch = engine.container.resolve(AgentOrchestrator)  # type: ignore[type-abstract]
    result = await orch.dispatch(
        AgentTask(description="Write code to implement parse_csv function", domain="programming")
    )
    assert result.success
    assert "def " in result.output or "scaffold" in result.output.lower()


@pytest.mark.asyncio
async def test_cross_agent_collaboration(engine: SageEngine) -> None:
    orch = engine.container.resolve(AgentOrchestrator)  # type: ignore[type-abstract]
    result = await orch.dispatch(
        AgentTask(
            description="Create irrigation plan for tomatoes and estimate the cost budget",
            domain="agriculture",
        )
    )
    assert result.success
    # Should include agriculture plan and possibly finance collab section
    assert "irrigation" in result.output.lower() or "water" in result.output.lower()
    # Collaboration may add finance section when cost/budget present
    assert "cost" in result.output.lower() or "budget" in result.output.lower() or "Finance" in result.output


@pytest.mark.asyncio
async def test_workflow_library_shared(engine: SageEngine) -> None:
    lib = engine.container.resolve(WorkflowLibrary)
    wfs = lib.list_workflows()
    assert len(wfs) >= 15
    agri = lib.list_workflows(domain="agriculture")
    assert any("irrigation" in w.id for w in agri)


@pytest.mark.asyncio
async def test_orchestrator_routes_agriculture(engine: SageEngine) -> None:
    reply = await engine.ask("Create irrigation plan for greenhouse tomatoes")
    assert reply
    assert any(k in reply.lower() for k in ("irrigation", "water", "agriculture", "schedule"))

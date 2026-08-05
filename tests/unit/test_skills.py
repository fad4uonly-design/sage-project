"""Shared Skill Library tests (v0.3.2)."""

from __future__ import annotations

import pytest

from sage.agents.interfaces import AgentOrchestrator, AgentTask
from sage.core.engine import SageEngine
from sage.skills.interfaces import SkillLibrary
from sage.skills.models import SkillCategory


@pytest.mark.asyncio
async def test_skills_module_loaded(engine: SageEngine) -> None:
    lib = engine.container.resolve(SkillLibrary)  # type: ignore[type-abstract]
    manifests = lib.list_skills()
    assert len(manifests) >= 12
    cats = {m.category for m in manifests}
    assert SkillCategory.ANALYSIS in cats
    assert SkillCategory.PLANNING in cats
    assert SkillCategory.DECISION in cats
    assert SkillCategory.REPORTING in cats
    assert SkillCategory.COMMUNICATION in cats


@pytest.mark.asyncio
async def test_swot_skill_invoke(engine: SageEngine) -> None:
    lib = engine.container.resolve(SkillLibrary)  # type: ignore[type-abstract]
    result = await lib.invoke(
        "skill_analysis_swot",
        task="SWOT for organic vegetable expansion",
        context={"memories": ["We sell at two markets"], "graph_facts": []},
    )
    assert result.success
    assert "strength" in result.output.lower()
    assert result.confidence > 0


@pytest.mark.asyncio
async def test_match_and_invoke_best(engine: SageEngine) -> None:
    lib = engine.container.resolve(SkillLibrary)  # type: ignore[type-abstract]
    matches = lib.match("draft an email to the supplier", limit=3)
    assert matches
    assert matches[0][0].manifest.id == "skill_comm_email"
    best = await lib.invoke_best("draft an email about delayed delivery")
    assert best is not None
    assert best.success
    assert "subject" in best.output.lower() or "email" in best.output.lower()


@pytest.mark.asyncio
async def test_weighted_comparison_uses_decision_engine(engine: SageEngine) -> None:
    lib = engine.container.resolve(SkillLibrary)  # type: ignore[type-abstract]
    result = await lib.invoke(
        "skill_decision_weighted",
        task="Choose equipment vendor",
        params={"options": ["Vendor A", "Vendor B", "Vendor C"]},
    )
    assert result.success
    assert "decision" in result.output.lower() or "ranking" in result.output.lower()
    assert "recommend" in result.output.lower()


@pytest.mark.asyncio
async def test_crop_planning_skill(engine: SageEngine) -> None:
    lib = engine.container.resolve(SkillLibrary)  # type: ignore[type-abstract]
    result = await lib.invoke(
        "skill_planning_crop",
        task="crop plan for tomatoes",
        context={"graph_facts": ["Tomato —requires→ Water"]},
    )
    assert result.success
    assert "tomato" in result.output.lower()
    assert result.data.get("crop") == "tomato"


@pytest.mark.asyncio
async def test_agent_can_orchestrate_skill(engine: SageEngine) -> None:
    """Domain agent falls through to skill library when no domain workflow wins."""
    orch = engine.container.resolve(AgentOrchestrator)  # type: ignore[type-abstract]
    # "meeting notes" is a shared skill, not a strong domain workflow
    result = await orch.dispatch(
        AgentTask(description="meeting notes for weekly leadership sync", domain="business")
    )
    assert result.success
    assert "meeting" in result.output.lower() or "action" in result.output.lower()


@pytest.mark.asyncio
async def test_list_by_category(engine: SageEngine) -> None:
    lib = engine.container.resolve(SkillLibrary)  # type: ignore[type-abstract]
    analysis = lib.list_skills(category=SkillCategory.ANALYSIS)
    assert len(analysis) >= 3
    assert all(m.category == SkillCategory.ANALYSIS for m in analysis)


@pytest.mark.asyncio
async def test_unknown_skill(engine: SageEngine) -> None:
    lib = engine.container.resolve(SkillLibrary)  # type: ignore[type-abstract]
    result = await lib.invoke("skill_does_not_exist", task="x")
    assert not result.success
    assert result.error

"""Cognitive Context Engine tests (v0.5.0)."""

from __future__ import annotations

import pytest

from sage.context.engine import CognitiveContextEngine
from sage.core.engine import SageEngine
from sage.goals.engine import GoalEngine, GoalHorizon
from sage.projects.manager import ProjectManager
from sage.reflection.engine import ReflectionEngine


@pytest.mark.asyncio
async def test_context_modules_loaded(engine: SageEngine) -> None:
    names = set(engine.registry.names())
    for m in ("projects", "goals", "context", "reflection"):
        assert m in names


@pytest.mark.asyncio
async def test_project_crud(engine: SageEngine) -> None:
    pm = engine.container.resolve(ProjectManager)  # type: ignore[type-abstract]
    p = await pm.create(
        "SAGE",
        description="Personal AI OS",
        priority=0.9,
        domain="programming",
        objectives=["Ship v1.0"],
        tags=["ai", "os"],
    )
    assert p.id
    got = await pm.get(p.id)
    assert got is not None
    assert got.name == "SAGE"
    await pm.link(p.id, "note", "note-1", title="Kickoff")
    links = await pm.links(p.id)
    assert len(links) == 1
    found = await pm.search("SAGE")
    assert any(x.id == p.id for x in found)


@pytest.mark.asyncio
async def test_goal_engine_tree(engine: SageEngine) -> None:
    ge = engine.container.resolve(GoalEngine)  # type: ignore[type-abstract]
    root = await ge.create(
        "Build AI Operating System",
        horizon=GoalHorizon.LONG,
        priority=0.95,
        success_metrics=["stable APIs", "offline-first"],
    )
    child = await ge.create(
        "Finish Context Engine",
        horizon=GoalHorizon.MEDIUM,
        parent_id=root.id,
        priority=0.8,
    )
    daily = await ge.create(
        "Write context tests",
        horizon=GoalHorizon.DAILY,
        parent_id=child.id,
        priority=0.7,
    )
    tree = await ge.tree(root.id)
    assert tree["goal"]["id"] == root.id
    assert len(tree["children"]) >= 1
    completed = await ge.complete(daily.id)
    assert completed.status.value == "completed"
    assert completed.progress == 1.0


@pytest.mark.asyncio
async def test_context_fusion_and_suggestions(engine: SageEngine) -> None:
    pm = engine.container.resolve(ProjectManager)  # type: ignore[type-abstract]
    ge = engine.container.resolve(GoalEngine)  # type: ignore[type-abstract]
    cce = engine.container.resolve(CognitiveContextEngine)  # type: ignore[type-abstract]

    project = await pm.create("AutoWise", description="Vehicle decision platform", priority=0.85)
    await cce.set_active_project(project.id)
    await ge.create("Vehicle Decision Platform", horizon="long", project_id=project.id, priority=0.9)
    await ge.create("Review irrigation notes", horizon="daily", priority=0.6)
    await cce.record_interest("agriculture", weight=0.5)
    await cce.record_interest("irrigation", weight=0.3)

    unified = await cce.fuse()
    assert unified.summary
    assert any(p["id"] == project.id for p in unified.active_projects)
    assert unified.session.active_project_id == project.id
    assert "agriculture" in " ".join(unified.long_term_interests).lower() or unified.long_term_interests

    created = await cce.generate_suggestions()
    # at least daily goal suggestion or project-related
    open_s = await cce.suggestions(limit=20)
    assert isinstance(created, list)
    assert isinstance(open_s, list)

    orch_ctx = unified.as_orchestrator_context()
    assert orch_ctx.get("unified_context") is True
    assert "context_summary" in orch_ctx


@pytest.mark.asyncio
async def test_session_continuity_snapshot(engine: SageEngine) -> None:
    cce = engine.container.resolve(CognitiveContextEngine)  # type: ignore[type-abstract]
    cont = await cce.continuity()
    assert cont.updated_at
    snap = await cce.snapshot(kind="test")
    assert snap.id
    assert snap.payload


@pytest.mark.asyncio
async def test_reflection_engine(engine: SageEngine) -> None:
    # Generate some audit activity via a tiny workflow if available
    try:
        from sage.workflow.engine import WorkflowEngine

        wf = engine.container.resolve(WorkflowEngine)  # type: ignore[type-abstract]
        await wf.start(
            "document_ingest_chain",
            context={"path": "/tmp/demo.md", "task": "demo doc"},
            principal="test",
        )
    except Exception:
        pass

    re_ = engine.container.resolve(ReflectionEngine)  # type: ignore[type-abstract]
    reflection = await re_.reflect()
    assert reflection.id
    assert reflection.findings
    assert reflection.recommendations
    text = reflection.format()
    assert "Findings" in text
    recent = await re_.list_recent(limit=5)
    assert any(r.id == reflection.id for r in recent)


@pytest.mark.asyncio
async def test_ask_context_suggestions(engine: SageEngine) -> None:
    pm = engine.container.resolve(ProjectManager)  # type: ignore[type-abstract]
    await pm.create("SAGE", description="AI OS", priority=0.9)
    reply = await engine.ask("what needs attention?")
    assert reply
    lower = reply.lower()
    assert "context" in lower or "suggestion" in lower or "project" in lower or "priority" in lower

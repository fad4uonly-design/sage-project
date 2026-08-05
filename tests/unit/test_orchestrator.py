"""Orchestrator tests."""

from __future__ import annotations

import pytest

from sage.core.engine import SageEngine
from sage.orchestrator.interfaces import Orchestrator
from sage.orchestrator.models import IntentKind


@pytest.mark.asyncio
async def test_intent_remember(engine: SageEngine) -> None:
    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]
    intent = await orch.analyze_intent("remember: water the tomatoes daily")
    assert intent.kind == IntentKind.REMEMBER
    assert "tomatoes" in intent.subject.lower()


@pytest.mark.asyncio
async def test_handle_remember_recall(engine: SageEngine) -> None:
    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]
    r1 = await orch.handle("remember: SAGE orchestrator routes all cognition")
    assert "remember" in r1.response.lower() or "orchestrator" in r1.response.lower()
    assert r1.intent.kind == IntentKind.REMEMBER
    assert r1.steps

    r2 = await orch.handle("what do you remember about orchestrator")
    assert "orchestrator" in r2.response.lower()
    assert r2.intent.kind == IntentKind.RECALL


@pytest.mark.asyncio
async def test_handle_plan(engine: SageEngine) -> None:
    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]
    result = await orch.handle("plan a greenhouse expansion")
    assert result.intent.kind == IntentKind.PLAN
    assert "step" in result.response.lower() or "1." in result.response

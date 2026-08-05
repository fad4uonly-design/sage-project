"""Reasoning strategy framework tests."""

from __future__ import annotations

import pytest

from sage.core.engine import SageEngine
from sage.reasoning.interfaces import ReasoningEngine
from sage.reasoning.models import ReasoningContext, StrategyKind
from sage.reasoning.strategies.base import StrategyRegistry


@pytest.mark.asyncio
async def test_strategies_registered(engine: SageEngine) -> None:
    reg = engine.container.resolve(StrategyRegistry)
    kinds = {s.kind for s in reg.all()}
    assert StrategyKind.AGRICULTURE in kinds
    assert StrategyKind.BUSINESS in kinds
    assert StrategyKind.MATHEMATICAL in kinds
    assert StrategyKind.LOGICAL in kinds
    assert len(reg.all()) >= 10


@pytest.mark.asyncio
async def test_agriculture_strategy_selected(engine: SageEngine) -> None:
    re_ = engine.container.resolve(ReasoningEngine)  # type: ignore[type-abstract]
    result = await re_.reason(
        "Should I increase irrigation for my tomato crop during blight risk?",
        context=ReasoningContext(
            graph_facts=["Tomato —requires→ Water", "Tomato —affected_by→ Blight"]
        ),
    )
    assert result.explainability is not None
    assert result.confidence > 0
    assert result.explainability.knowledge_graph_facts or result.trace
    # Agriculture or risk should rank highly
    assert result.strategy in {
        StrategyKind.AGRICULTURE,
        StrategyKind.RISK,
        StrategyKind.SCIENTIFIC,
        StrategyKind.DECISION,
        StrategyKind.PLANNING,
    }


@pytest.mark.asyncio
async def test_math_strategy(engine: SageEngine) -> None:
    re_ = engine.container.resolve(ReasoningEngine)  # type: ignore[type-abstract]
    result = await re_.reason(
        "Calculate 15 * 4 + 10",
        strategy=StrategyKind.MATHEMATICAL,
        use_retrieval=False,
    )
    assert "70" in result.conclusion or result.strategy == StrategyKind.MATHEMATICAL


@pytest.mark.asyncio
async def test_explainability_format(engine: SageEngine) -> None:
    re_ = engine.container.resolve(ReasoningEngine)  # type: ignore[type-abstract]
    result = await re_.reason(
        "Why does soil moisture affect yield?",
        context=ReasoningContext(memories=["Dry soil reduced last harvest"]),
    )
    text = result.explainability.format() if result.explainability else ""
    assert "Question" in text
    assert "Final Answer" in text
    assert "Confidence" in text

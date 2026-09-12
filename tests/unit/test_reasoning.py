"""Reasoning engine tests."""

from __future__ import annotations

import pytest
from sage.core.engine import SageEngine
from sage.reasoning.interfaces import ReasoningEngine
from sage.reasoning.models import ReasoningContext, StrategyKind


@pytest.mark.asyncio
async def test_reason_returns_trace(engine: SageEngine) -> None:
    re_ = engine.container.resolve(ReasoningEngine)  # type: ignore[type-abstract]
    result = await re_.reason(
        "Should I expand the farm this season?",
        context=ReasoningContext(facts=["Budget is limited", "Soil tests are good"]),
    )
    assert result.conclusion
    assert len(result.trace) >= 2
    assert result.strategy in StrategyKind


@pytest.mark.asyncio
async def test_decision_strategy(engine: SageEngine) -> None:
    re_ = engine.container.resolve(ReasoningEngine)  # type: ignore[type-abstract]
    result = await re_.reason("Should I choose option A or B?", strategy=StrategyKind.DECISION)
    assert result.strategy == StrategyKind.DECISION
    assert result.alternatives

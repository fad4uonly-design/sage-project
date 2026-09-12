"""Decision engine tests."""

from __future__ import annotations

import pytest
from sage.core.engine import SageEngine
from sage.decision.engine import DecisionEngine
from sage.decision.models import Criterion, DecisionOption, DecisionRequest


@pytest.mark.asyncio
async def test_weighted_ranking(engine: SageEngine) -> None:
    de = engine.container.resolve(DecisionEngine)  # type: ignore[type-abstract]
    result = await de.decide(
        DecisionRequest(
            question="Pick a pump",
            criteria=[
                Criterion(id="cost", name="Cost", weight=0.5, maximize=False),
                Criterion(id="reliability", name="Reliability", weight=0.5),
            ],
            options=[
                DecisionOption(id="a", name="Cheap", scores={"cost": 100, "reliability": 0.4}),
                DecisionOption(id="b", name="Premium", scores={"cost": 300, "reliability": 0.95}),
                DecisionOption(
                    id="c",
                    name="Mid",
                    scores={"cost": 180, "reliability": 0.8},
                    risks=["Lead time"],
                ),
            ],
        )
    )
    assert result.ranking
    assert result.ranking[0].rank == 1
    assert result.recommendation
    assert 0 < result.confidence <= 1
    text = result.format()
    assert "Decision Analysis" in text
    assert "Ranking" in text


@pytest.mark.asyncio
async def test_quick_rank(engine: SageEngine) -> None:
    de = engine.container.resolve(DecisionEngine)  # type: ignore[type-abstract]
    result = await de.quick_rank("Choose path", ["Alpha", "Beta", "Gamma"])
    assert len(result.ranking) == 3

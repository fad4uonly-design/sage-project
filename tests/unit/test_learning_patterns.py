"""Learning pattern tests."""

from __future__ import annotations

import pytest

from sage.core.engine import SageEngine
from sage.learning.interfaces import LearningEngine
from sage.learning.models import Observation, ObservationKind
from sage.learning.service import DefaultLearningEngine


@pytest.mark.asyncio
async def test_pattern_detection(engine: SageEngine) -> None:
    learn = engine.container.resolve(DefaultLearningEngine)
    await learn.observe(
        Observation(
            kind=ObservationKind.CONVERSATION,
            content="I water the farm every day and check soil moisture daily",
        )
    )
    await learn.observe(
        Observation(
            kind=ObservationKind.CONVERSATION,
            content="I prefer detailed irrigation reports for the crop farm",
        )
    )
    patterns = await learn.list_patterns(limit=20)
    assert patterns
    # domain or workflow should appear
    types = {p["pattern_type"] for p in patterns}
    assert types & {"workflow", "preference_cue", "domain_interest"}


@pytest.mark.asyncio
async def test_find_patterns_api(engine: SageEngine) -> None:
    learn = engine.container.resolve(LearningEngine)  # type: ignore[type-abstract]
    eng = engine.container.resolve(DefaultLearningEngine)
    await eng.observe(
        Observation(
            kind=ObservationKind.CONVERSATION,
            content="Weekly budget review for finance and revenue tracking",
        )
    )
    found = await eng.find_patterns("finance", limit=5)
    assert isinstance(found, list)

"""Planning engine tests."""

from __future__ import annotations

import pytest
from sage.core.engine import SageEngine
from sage.planning.interfaces import PlanningEngine


@pytest.mark.asyncio
async def test_create_goal_and_plan(engine: SageEngine) -> None:
    pe = engine.container.resolve(PlanningEngine)  # type: ignore[type-abstract]
    goal = await pe.create_goal("Launch a small organic herb business")
    plan = await pe.plan(goal.id)
    assert plan.goal_id == goal.id
    assert len(plan.steps) >= 3
    progress = await pe.track(plan.id)
    assert progress.total_steps >= 3
    assert progress.percent_complete == 0.0

"""Planning engine protocol."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from sage.planning.models import Goal, Plan, PlanProgress


@runtime_checkable
class PlanningEngine(Protocol):
    async def create_goal(self, description: str, **kwargs: Any) -> Goal: ...

    async def plan(self, goal_id: str) -> Plan: ...

    async def prioritize(self, task_ids: Sequence[str]) -> list[str]: ...

    async def track(self, plan_id: str) -> PlanProgress: ...

"""Goals module."""

from __future__ import annotations

from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.db.connection import Database
from sage.goals.engine import GoalEngine, SQLiteGoalEngine


class GoalsModule(BaseModule):
    name = "goals"
    version = "0.5.0"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._engine: SQLiteGoalEngine | None = None

    async def _on_initialize(self) -> None:
        db = self.container.resolve(Database)
        self._engine = SQLiteGoalEngine(db)
        self.container.register_instance(GoalEngine, self._engine)
        self.container.register_instance(SQLiteGoalEngine, self._engine)

    async def _on_health(self) -> HealthStatus | None:
        if self._engine is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        active = await self._engine.list(status="active", limit=500)
        return HealthStatus.healthy(self.name, "ok", active_goals=len(active))

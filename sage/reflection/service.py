"""Reflection module."""

from __future__ import annotations

from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.core.scheduler import Scheduler
from sage.db.connection import Database
from sage.logging import get_logger
from sage.reflection.engine import DefaultReflectionEngine, ReflectionEngine

log = get_logger(__name__)


class ReflectionModule(BaseModule):
    name = "reflection"
    version = "0.5.0"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._engine: DefaultReflectionEngine | None = None

    async def _on_initialize(self) -> None:
        db = self.container.resolve(Database)
        self._engine = DefaultReflectionEngine(db, self.container)
        self.container.register_instance(ReflectionEngine, self._engine)
        self.container.register_instance(DefaultReflectionEngine, self._engine)

    async def _on_start(self) -> None:
        scheduler = self.container.try_resolve(Scheduler)
        if scheduler and self._engine:
            eng = self._engine

            async def _job() -> None:
                await eng.reflect()

            scheduler.register(
                "reflection.daily",
                _job,
                daily_at="04:15",
                description="Daily system reflection over audits and workflows",
            )

    async def _on_health(self) -> HealthStatus | None:
        if self._engine is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        recent = await self._engine.list_recent(limit=1)
        return HealthStatus.healthy(self.name, "ok", has_reflections=bool(recent))

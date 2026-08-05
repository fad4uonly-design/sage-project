"""Cognitive Context module."""

from __future__ import annotations

from sage.context.engine import CognitiveContextEngine, DefaultCognitiveContextEngine
from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.core.scheduler import Scheduler
from sage.db.connection import Database
from sage.logging import get_logger

log = get_logger(__name__)


class ContextModule(BaseModule):
    name = "context"
    version = "0.5.0"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._engine: DefaultCognitiveContextEngine | None = None

    async def _on_initialize(self) -> None:
        db = self.container.resolve(Database)
        self._engine = DefaultCognitiveContextEngine(db, self.container)
        self.container.register_instance(CognitiveContextEngine, self._engine)  # type: ignore[type-abstract]
        self.container.register_instance(DefaultCognitiveContextEngine, self._engine)

    async def _on_start(self) -> None:
        if self._engine:
            try:
                await self._engine.bootstrap_session()
            except Exception:
                log.exception("context.bootstrap_failed")

        scheduler = self.container.try_resolve(Scheduler)
        if scheduler and self._engine:
            eng = self._engine

            async def _refresh() -> None:
                await eng.generate_suggestions()
                await eng.snapshot(kind="periodic")

            scheduler.register(
                "context.refresh_suggestions",
                _refresh,
                interval_seconds=3600.0,
                description="Refresh proactive suggestions hourly",
            )

    async def _on_health(self) -> HealthStatus | None:
        if self._engine is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        ctx = await self._engine.fuse()
        return HealthStatus.healthy(
            self.name,
            "ok",
            projects=len(ctx.active_projects),
            goals=len(ctx.goals),
            suggestions=len(ctx.suggestions),
        )

"""Discovery module."""

from __future__ import annotations

from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.core.scheduler import Scheduler
from sage.db.connection import Database
from sage.discovery.engine import DefaultDiscoveryEngine, DiscoveryEngine
from sage.logging import get_logger

log = get_logger(__name__)


class DiscoveryModule(BaseModule):
    name = "discovery"
    version = "0.6.0"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._engine: DefaultDiscoveryEngine | None = None

    async def _on_initialize(self) -> None:
        db = self.container.resolve(Database)
        # Ensure insights table exists (additive; also in v6 migration)
        try:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS discovery_insights (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0.5,
                    evidence TEXT NOT NULL DEFAULT '[]',
                    recommendations TEXT NOT NULL DEFAULT '[]',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_discovery_created
                    ON discovery_insights(created_at);
                """
            )
        except Exception:
            log.exception("discovery.table_init_failed")
        self._engine = DefaultDiscoveryEngine(db, self.container)
        self.container.register_instance(DiscoveryEngine, self._engine)  # type: ignore[type-abstract]
        self.container.register_instance(DefaultDiscoveryEngine, self._engine)

    async def _on_start(self) -> None:
        scheduler = self.container.try_resolve(Scheduler)
        if scheduler and self._engine:
            eng = self._engine

            async def _job() -> None:
                await eng.discover(limit=15)

            scheduler.register(
                "discovery.periodic",
                _job,
                interval_seconds=7200.0,
                description="Knowledge discovery every 2 hours",
            )

    async def _on_health(self) -> HealthStatus | None:
        if self._engine is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        recent = await self._engine.list_recent(limit=1)
        return HealthStatus.healthy(self.name, "ok", has_insights=bool(recent))

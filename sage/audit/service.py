"""Audit module."""

from __future__ import annotations

from sage.audit.logger import AuditLogger, ExecutionAudit
from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.db.connection import Database
from sage.events.bus import EventBus


class AuditModule(BaseModule):
    name = "audit"
    version = "0.4.0"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._logger: AuditLogger | None = None

    async def _on_initialize(self) -> None:
        db = self.container.resolve(Database)
        events = self.container.try_resolve(EventBus)  # type: ignore[type-abstract]
        self._logger = AuditLogger(db, events)
        self.container.register_instance(ExecutionAudit, self._logger)  # type: ignore[type-abstract]
        self.container.register_instance(AuditLogger, self._logger)

    async def _on_health(self) -> HealthStatus | None:
        if self._logger is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        recent = await self._logger.list_recent(limit=1)
        return HealthStatus.healthy(self.name, "ok", has_records=bool(recent))

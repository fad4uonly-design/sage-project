"""Approval module."""

from __future__ import annotations

from sage.approval.engine import ApprovalEngine, DefaultApprovalEngine
from sage.approval.models import ApprovalLevel
from sage.config.settings import Settings
from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.db.connection import Database
from sage.events.bus import EventBus


class ApprovalModule(BaseModule):
    name = "approval"
    version = "0.4.0"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._engine: DefaultApprovalEngine | None = None

    async def _on_initialize(self) -> None:
        db = self.container.resolve(Database)
        events = self.container.try_resolve(EventBus)  # type: ignore[type-abstract]
        settings = self.container.resolve(Settings)
        self._engine = DefaultApprovalEngine(db, events)
        self.container.register_instance(ApprovalEngine, self._engine)  # type: ignore[type-abstract]
        self.container.register_instance(DefaultApprovalEngine, self._engine)

        # Safe defaults for core tools
        await self._engine.set_policy("tool", "echo", ApprovalLevel.AUTOMATIC)
        await self._engine.set_policy("tool", "current_time", ApprovalLevel.AUTOMATIC)
        await self._engine.set_policy("tool", "calculator", ApprovalLevel.AUTOMATIC)
        await self._engine.set_policy("skill", "*", ApprovalLevel.AUTOMATIC)
        if settings.env == "test":
            # Tests auto-approve sensitive ops via check(auto_approve_in_test=True)
            await self._engine.set_policy("tool", "write_file", ApprovalLevel.ASK_ONCE)
            await self._engine.set_policy("tool", "read_file", ApprovalLevel.AUTOMATIC)

    async def _on_health(self) -> HealthStatus | None:
        if self._engine is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        pending = await self._engine.list_pending()
        return HealthStatus.healthy(self.name, "ok", pending=len(pending))

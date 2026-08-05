"""Projects module."""

from __future__ import annotations

from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.db.connection import Database
from sage.projects.manager import ProjectManager, SQLiteProjectManager


class ProjectsModule(BaseModule):
    name = "projects"
    version = "0.5.0"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._mgr: SQLiteProjectManager | None = None

    async def _on_initialize(self) -> None:
        db = self.container.resolve(Database)
        self._mgr = SQLiteProjectManager(db)
        self.container.register_instance(ProjectManager, self._mgr)  # type: ignore[type-abstract]
        self.container.register_instance(SQLiteProjectManager, self._mgr)

    async def _on_health(self) -> HealthStatus | None:
        if self._mgr is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        items = await self._mgr.list(limit=1000)
        active = sum(1 for p in items if p.status.value == "active")
        return HealthStatus.healthy(self.name, "ok", projects=len(items), active=active)

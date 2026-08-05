"""Database module — opens SQLite and runs migrations on boot."""

from __future__ import annotations

from sage.config.settings import Settings
from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.db.connection import Database
from sage.db.migrations import apply_migrations, current_version
from sage.logging import get_logger

log = get_logger(__name__)


class DatabaseModule(BaseModule):
    name = "database"
    version = "0.1.0"
    is_critical = True

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._db: Database | None = None
        self._schema_version: int = 0

    async def _on_initialize(self) -> None:
        settings = self.container.resolve(Settings)
        self._db = Database(settings.db_path)
        await self._db.open()
        self._schema_version = await apply_migrations(self._db)
        self.container.register_instance(Database, self._db)
        log.info("database.ready", path=str(settings.db_path), schema=self._schema_version)

    async def _on_shutdown(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def _on_health(self) -> HealthStatus | None:
        if self._db is None or not self._db.is_open:
            return HealthStatus.unhealthy(self.name, "database not open", critical=True)
        try:
            ver = await current_version(self._db)
            return HealthStatus.healthy(
                self.name,
                "connected",
                schema_version=ver,
                path=str(self._db.path),
            )
        except Exception as exc:
            return HealthStatus.unhealthy(self.name, str(exc), critical=True)

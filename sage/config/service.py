"""Configuration module — exposes ConfigurationManager in the DI graph."""

from __future__ import annotations

from sage.config.manager import ConfigurationManager
from sage.config.settings import Settings
from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.db.connection import Database


class ConfigModule(BaseModule):
    name = "config"
    version = "0.1.1"
    is_critical = True

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._mgr: ConfigurationManager | None = None

    async def _on_initialize(self) -> None:
        settings = self.container.resolve(Settings)
        db = self.container.try_resolve(Database)
        self._mgr = ConfigurationManager(settings, db)
        if db:
            await self._mgr.load_profile("default")
        self.container.register_instance(ConfigurationManager, self._mgr)

    async def _on_health(self) -> HealthStatus | None:
        if self._mgr is None:
            return HealthStatus.unhealthy(self.name, "not initialized", critical=True)
        return HealthStatus.healthy(
            self.name,
            "ok",
            env=self._mgr.settings.env,
            profile=self._mgr.profile,
        )

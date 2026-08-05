"""Plugin module."""

from __future__ import annotations

from sage.config.settings import Settings
from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.plugins.manager import PluginManager


class PluginModule(BaseModule):
    name = "plugins"
    version = "0.1.0"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._manager: PluginManager | None = None
        self._loaded: list[str] = []

    async def _on_initialize(self) -> None:
        settings = self.container.resolve(Settings)
        self._manager = PluginManager(self.container)
        self.container.register_instance(PluginManager, self._manager)
        if settings.plugins.enabled and settings.plugins.auto_load:
            self._loaded = await self._manager.load_from_directories(settings.plugins.directories)

    async def _on_shutdown(self) -> None:
        if self._manager:
            await self._manager.unload_all()

    async def _on_health(self) -> HealthStatus | None:
        if self._manager is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        return HealthStatus.healthy(self.name, "ok", loaded=len(self._manager.loaded))

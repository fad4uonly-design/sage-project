"""Models module."""

from __future__ import annotations

from sage.config.settings import Settings
from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.models.interfaces import ModelRouter
from sage.models.router import DefaultModelRouter


class ModelsModule(BaseModule):
    name = "models"
    version = "0.1.0"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._router: DefaultModelRouter | None = None

    async def _on_initialize(self) -> None:
        settings = self.container.resolve(Settings)
        self._router = DefaultModelRouter(settings)
        self.container.register_instance(ModelRouter, self._router)  # type: ignore[type-abstract]
        self.container.register_instance(DefaultModelRouter, self._router)

    async def _on_health(self) -> HealthStatus | None:
        if self._router is None:
            return HealthStatus.unhealthy(self.name, "router missing")
        lm = self._router.get_language_model()
        return HealthStatus.healthy(
            self.name,
            "ok",
            provider=lm.provider,
            model=lm.model_name,
        )

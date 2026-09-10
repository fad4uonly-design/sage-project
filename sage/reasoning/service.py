"""Reasoning module wiring."""

from __future__ import annotations

from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.models.interfaces import ModelRouter
from sage.reasoning.engine import DefaultReasoningEngine
from sage.reasoning.interfaces import ReasoningEngine
from sage.reasoning.strategies.base import StrategyRegistry


class ReasoningModule(BaseModule):
    name = "reasoning"
    version = "0.2.0"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._engine: DefaultReasoningEngine | None = None

    async def _on_initialize(self) -> None:
        models = self.container.try_resolve(ModelRouter)
        self._engine = DefaultReasoningEngine(models, container=self.container)
        self.container.register_instance(ReasoningEngine, self._engine)
        self.container.register_instance(DefaultReasoningEngine, self._engine)
        self.container.register_instance(StrategyRegistry, self._engine.registry)

    async def _on_health(self) -> HealthStatus | None:
        if self._engine is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        n = len(self._engine.registry.all())
        return HealthStatus.healthy(self.name, "ok", strategies=n)

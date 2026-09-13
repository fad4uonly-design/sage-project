"""Decision module."""

from __future__ import annotations

from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.decision.engine import DecisionEngine, DefaultDecisionEngine


class DecisionModule(BaseModule):
    name = "decision"
    version = "0.3.0"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._engine: DefaultDecisionEngine | None = None

    async def _on_initialize(self) -> None:
        self._engine = DefaultDecisionEngine()
        self.container.register_instance(DecisionEngine, self._engine)
        self.container.register_instance(DefaultDecisionEngine, self._engine)

    async def _on_health(self) -> HealthStatus | None:
        if self._engine is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        return HealthStatus.healthy(self.name, "ok")

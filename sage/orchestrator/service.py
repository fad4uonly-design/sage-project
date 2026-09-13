"""Orchestrator module wiring."""

from __future__ import annotations

from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.orchestrator.engine import DefaultOrchestrator
from sage.orchestrator.interfaces import Orchestrator


class OrchestratorModule(BaseModule):
    name = "orchestrator"
    version = "0.1.1"
    is_critical = True

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._orch: DefaultOrchestrator | None = None

    async def _on_initialize(self) -> None:
        self._orch = DefaultOrchestrator(self.container)
        self.container.register_instance(Orchestrator, self._orch)
        self.container.register_instance(DefaultOrchestrator, self._orch)

    async def _on_health(self) -> HealthStatus | None:
        if self._orch is None:
            return HealthStatus.unhealthy(self.name, "not initialized", critical=True)
        return HealthStatus.healthy(self.name, "ok")

"""Retrieval module."""

from __future__ import annotations

from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.retrieval.interfaces import Retriever
from sage.retrieval.pipeline import LayeredRetriever


class RetrievalModule(BaseModule):
    name = "retrieval"
    version = "0.2.0"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._retriever: LayeredRetriever | None = None

    async def _on_initialize(self) -> None:
        self._retriever = LayeredRetriever(self.container)
        self.container.register_instance(Retriever, self._retriever)  # type: ignore[type-abstract]
        self.container.register_instance(LayeredRetriever, self._retriever)

    async def _on_health(self) -> HealthStatus | None:
        if self._retriever is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        return HealthStatus.healthy(self.name, "ok")

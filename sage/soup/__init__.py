"""SOUP subsystem — Small Offline Uniform Probe experiment comparison."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sage.core.module import BaseModule
from sage.db.connection import Database
from sage.events.bus import EventBus
from sage.evolver.service import EvolverRepository
from sage.soup.interfaces import SoupEngine
from sage.soup.service import SoupService

if TYPE_CHECKING:
    from sage.core.container import Container

__all__ = [
    "SoupEngine",
    "SoupModule",
    "SoupService",
]


class SoupModule(BaseModule):
    """SOUP module implementing BaseModule lifecycle."""

    def __init__(
        self,
        db: Database,
        evolver_repo: EvolverRepository,
        events: EventBus | None = None,
    ) -> None:
        super().__init__(name="soup")
        self._db = db
        self._evolver_repo = evolver_repo
        self._events = events
        self._service: SoupService | None = None

    async def _on_initialize(self) -> None:
        """Initialize SOUP service."""
        self._service = SoupService(self._db, self._evolver_repo, events=self._events)
        self._logger.info("soup.initialized")

    async def _on_start(self) -> None:
        """Start SOUP subsystem."""
        self._logger.info("soup.started")

    async def _on_stop(self) -> None:
        """Stop SOUP subsystem."""
        self._logger.info("soup.stopped")

    async def _on_shutdown(self) -> None:
        """Shutdown SOUP subsystem."""
        self._service = None
        self._logger.info("soup.shutdown")

    async def _on_health(self) -> dict:
        """Health check for SOUP subsystem."""
        if self._service is None:
            return {"status": "not_initialized"}
        return {"status": "healthy"}

    @property
    def service(self) -> SoupService:
        """Access the SOUP service."""
        if self._service is None:
            raise RuntimeError("SoupModule not initialized")
        return self._service

    @classmethod
    def register(cls, container: Container) -> None:
        """Register SOUP module and services in the container."""
        from sage.soup.interfaces import SoupEngine

        def factory() -> SoupModule:
            db = container.resolve(Database)
            evolver_repo = container.resolve(EvolverRepository)
            events = container.resolve(EventBus, optional=True)
            return cls(db, evolver_repo, events)

        container.register_factory(SoupModule, factory)
        container.register_factory(
            SoupEngine,
            lambda: container.resolve(SoupModule).service,
        )

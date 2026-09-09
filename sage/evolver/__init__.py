"""Evolver subsystem — self-improvement variant iteration and lineage tracking."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sage.audit.logger import AuditLogger
from sage.core.module import BaseModule
from sage.db.connection import Database
from sage.events.bus import EventBus
from sage.evolver.interfaces import Evolver
from sage.evolver.service import (
    ApplicationService,
    EvolverRepository,
    EvolverService,
    ProposalService,
)

if TYPE_CHECKING:
    from sage.core.container import Container

__all__ = [
    "Evolver",
    "EvolverModule",
    "EvolverService",
    "ProposalService",
    "ApplicationService",
]


class EvolverModule(BaseModule):
    """Evolver module implementing BaseModule lifecycle."""

    def __init__(
        self,
        db: Database,
        audit: AuditLogger,
        events: EventBus | None = None,
    ) -> None:
        super().__init__(name="evolver")
        self._db = db
        self._audit = audit
        self._events = events
        self._service: EvolverService | None = None

    async def _on_initialize(self) -> None:
        """Initialize evolver repository and services."""
        repo = EvolverRepository(self._db)
        proposer = ProposalService(repo, events=self._events)
        applier = ApplicationService(repo, self._audit, events=self._events)
        self._service = EvolverService(repo, proposer, applier, events=self._events)
        self._logger.info("evolver.initialized")

    async def _on_start(self) -> None:
        """Start evolver subsystem."""
        self._logger.info("evolver.started")

    async def _on_stop(self) -> None:
        """Stop evolver subsystem."""
        self._logger.info("evolver.stopped")

    async def _on_shutdown(self) -> None:
        """Shutdown evolver subsystem."""
        self._service = None
        self._logger.info("evolver.shutdown")

    async def _on_health(self) -> dict:
        """Health check for evolver subsystem."""
        if self._service is None:
            return {"status": "not_initialized"}

        active_variant = await self._service.get_active_variant()
        candidates = await self._service.list_variants(status="candidate", limit=10)

        return {
            "status": "healthy",
            "active_variant_id": active_variant.id if active_variant else None,
            "candidate_count": len(candidates),
        }

    @property
    def service(self) -> EvolverService:
        """Access the evolver service."""
        if self._service is None:
            raise RuntimeError("EvolverModule not initialized")
        return self._service

    @classmethod
    def register(cls, container: Container) -> None:
        """Register evolver module and services in the container."""
        from sage.evolver.interfaces import Evolver

        def factory() -> EvolverModule:
            db = container.resolve(Database)
            audit = container.resolve(AuditLogger)
            events = container.resolve(EventBus, optional=True)
            return cls(db, audit, events)

        container.register_factory(EvolverModule, factory)
        container.register_factory(
            Evolver,
            lambda: container.resolve(EvolverModule).service,
        )

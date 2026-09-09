"""Evolver service implementation — variant management with strict safety separation."""

from __future__ import annotations

import json
from typing import Any

from sage.audit.logger import AuditLogger
from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.db.connection import Database
from sage.db.repository import BaseRepository
from sage.events.bus import EventBus
from sage.events.events import Event
from sage.evolver.interfaces import Evolver, VariantApplier, VariantProposer
from sage.evolver.models import MutationRecord, PromotionEvidence, Variant, VariantStatus
from sage.logging import get_logger
from sage.utils.time import utcnow_iso

log = get_logger(__name__)


class EvolverRepository(BaseRepository):
    """Data access layer for evolver variants."""

    def __init__(self, db: Database) -> None:
        super().__init__(db)

    async def get_by_id(self, variant_id: str) -> Variant | None:
        row = await self.db.fetchone(
            "SELECT * FROM evolver_variants WHERE id = ?",
            (variant_id,),
        )
        if row is None:
            return None
        return self._row_to_variant(row)

    async def get_active(self) -> Variant | None:
        row = await self.db.fetchone(
            "SELECT * FROM evolver_variants WHERE status = ? ORDER BY updated_at DESC LIMIT 1",
            (VariantStatus.ACTIVE.value,),
        )
        if row is None:
            return None
        return self._row_to_variant(row)

    async def list_all(
        self,
        *,
        status: VariantStatus | None = None,
        limit: int = 50,
    ) -> list[Variant]:
        if status is not None:
            status_val = status.value if isinstance(status, VariantStatus) else status
            rows = await self.db.fetchall(
                "SELECT * FROM evolver_variants WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status_val, limit),
            )
        else:
            rows = await self.db.fetchall(
                "SELECT * FROM evolver_variants ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        return [self._row_to_variant(r) for r in rows]

    async def insert(self, variant: Variant) -> None:
        await self.db.execute(
            """
            INSERT INTO evolver_variants (
                id, name, generation, parent_id, payload, mutation, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                variant.id,
                variant.name,
                variant.generation,
                variant.parent_id,
                variant.payload,
                variant.mutation,
                variant.status.value if isinstance(variant.status, VariantStatus) else variant.status,
                variant.created_at,
                variant.updated_at,
            ),
        )

    async def update_status(self, variant_id: str, status: VariantStatus) -> None:
        now = utcnow_iso()
        status_val = status.value if isinstance(status, VariantStatus) else status
        await self.db.execute(
            "UPDATE evolver_variants SET status = ?, updated_at = ? WHERE id = ?",
            (status_val, now, variant_id),
        )

    def _row_to_variant(self, row: Any) -> Variant:
        return Variant(
            id=row["id"],
            name=row["name"],
            generation=row["generation"],
            parent_id=row["parent_id"],
            payload=row["payload"],
            mutation=row["mutation"],
            status=VariantStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class ProposalService(VariantProposer):
    """Isolated service dedicated strictly to proposing candidate variants.

    Safety Guarantee:
    - This class has NO ability to activate or promote variants.
    - Zero side effects on running systems.
    - Always creates variants in CANDIDATE status.
    """

    def __init__(self, repo: EvolverRepository, events: EventBus | None = None) -> None:
        self._repo = repo
        self._events = events

    async def propose_variant(
        self,
        *,
        name: str,
        payload: str,
        parent_id: str | None = None,
        mutation: MutationRecord | str | None = None,
    ) -> Variant:
        """Create and persist a new candidate proposal.

        Calculates generation monotonically from parent_id if supplied.
        Always creates variant with status=CANDIDATE.
        """
        generation = 0
        if parent_id is not None:
            parent = await self._repo.get_by_id(parent_id)
            if parent is not None:
                generation = parent.generation + 1

        mutation_text: str | None = None
        if isinstance(mutation, MutationRecord):
            mutation_text = mutation.model_dump_json()
        elif isinstance(mutation, str):
            mutation_text = mutation

        variant = Variant(
            name=name,
            generation=generation,
            parent_id=parent_id,
            payload=payload,
            mutation=mutation_text,
            status=VariantStatus.CANDIDATE,
        )

        await self._repo.insert(variant)
        log.info(
            "evolver.variant_proposed",
            id=variant.id,
            name=variant.name,
            generation=variant.generation,
            parent_id=variant.parent_id,
        )

        if self._events:
            await self._events.publish(
                Event(
                    type="evolver.variant_proposed",
                    payload={"variant_id": variant.id, "name": variant.name},
                    source="evolver",
                )
            )

        return variant


class ApplicationService(VariantApplier):
    """Isolated service dedicated strictly to activating approved variants.

    Safety Guarantee:
    - Requires explicit approval boolean (approved=True).
    - Requires valid PromotionEvidence where mean_score > baseline_mean_score.
    - Writes an append-only audit log entry BEFORE applying.
    - Demotes previously active variants to RETIRED or PROMOTED.
    """

    def __init__(
        self,
        repo: EvolverRepository,
        audit: AuditLogger,
        events: EventBus | None = None,
    ) -> None:
        self._repo = repo
        self._audit = audit
        self._events = events

    async def apply_variant(
        self,
        variant_id: str,
        *,
        approved: bool,
        evidence: PromotionEvidence,
        approver: str = "system",
        reason: str | None = None,
    ) -> Variant:
        """Activate a candidate variant after verifying promotion evidence and explicit approval."""
        if not approved:
            raise PermissionError(
                f"Variant {variant_id} cannot be applied: explicit approval flag is False."
            )

        # Evidence validation: must beat baseline
        if evidence.mean_score <= evidence.baseline_mean_score:
            raise ValueError(
                f"Promotion refused for variant {variant_id}: measured mean score "
                f"({evidence.mean_score}) does not beat baseline ({evidence.baseline_mean_score})."
            )

        variant = await self._repo.get_by_id(variant_id)
        if variant is None:
            raise KeyError(f"Variant not found: {variant_id}")

        if variant.status == VariantStatus.RETIRED:
            raise ValueError(f"Cannot apply retired variant: {variant_id}")

        # Write immutable audit log record before updating state
        await self._audit.record(
            kind="system",
            subject_id=variant.id,
            principal=approver,
            status="ok",
            summary=f"Evolver applied variant '{variant.name}' (gen {variant.generation})",
            reasoning=reason or f"SOUP run {evidence.run_id} evidence: {evidence.mean_score} vs {evidence.baseline_mean_score}",
            confidence=evidence.mean_score / 100.0 if evidence.mean_score <= 100 else 1.0,
            approvals=[approver],
            detail={
                "variant_id": variant.id,
                "variant_name": variant.name,
                "generation": variant.generation,
                "parent_id": variant.parent_id,
                "run_id": evidence.run_id,
                "mean_score": evidence.mean_score,
                "baseline_mean_score": evidence.baseline_mean_score,
                "cases_won": evidence.cases_won,
                "cases_lost": evidence.cases_lost,
                "cases_tied": evidence.cases_tied,
            },
        )

        # Deactivate existing active variant if any
        current_active = await self._repo.get_active()
        if current_active is not None and current_active.id != variant.id:
            await self._repo.update_status(current_active.id, VariantStatus.RETIRED)

        # Mark target variant as ACTIVE
        await self._repo.update_status(variant.id, VariantStatus.ACTIVE)
        updated_variant = await self._repo.get_by_id(variant.id)
        if updated_variant is None:
            raise RuntimeError(f"Failed to reload variant after update: {variant.id}")

        log.info(
            "evolver.variant_applied",
            id=variant.id,
            name=variant.name,
            generation=variant.generation,
            approver=approver,
        )

        if self._events:
            await self._events.publish(
                Event(
                    type="evolver.variant_applied",
                    payload={"variant_id": variant.id, "name": variant.name, "approver": approver},
                    source="evolver",
                )
            )

        return updated_variant


class EvolverService(Evolver):
    """Main Evolver subsystem coordinator implementing variant lifecycle queries."""

    def __init__(
        self,
        repo: EvolverRepository,
        proposer: ProposalService,
        applier: ApplicationService,
        events: EventBus | None = None,
    ) -> None:
        self._repo = repo
        self._proposer = proposer
        self._applier = applier
        self._events = events

    @property
    def proposer(self) -> ProposalService:
        """Access the isolated proposal service."""
        return self._proposer

    @property
    def applier(self) -> ApplicationService:
        """Access the isolated application service."""
        return self._applier

    async def get_variant(self, variant_id: str) -> Variant | None:
        return await self._repo.get_by_id(variant_id)

    async def get_active_variant(self) -> Variant | None:
        return await self._repo.get_active()

    async def list_variants(
        self,
        *,
        status: VariantStatus | None = None,
        limit: int = 50,
    ) -> list[Variant]:
        return await self._repo.list_all(status=status, limit=limit)

    async def get_lineage(self, variant_id: str) -> list[Variant]:
        """Fetch the full ancestral lineage for a variant from root to target."""
        lineage: list[Variant] = []
        current_id: str | None = variant_id

        visited: set[str] = set()
        while current_id is not None and current_id not in visited:
            visited.add(current_id)
            variant = await self._repo.get_by_id(current_id)
            if variant is None:
                break
            lineage.append(variant)
            current_id = variant.parent_id

        lineage.reverse()  # Root -> Target
        return lineage

    async def mark_evaluated(self, variant_id: str) -> Variant:
        """Mark a candidate variant as evaluated after completing eval trials."""
        variant = await self._repo.get_by_id(variant_id)
        if variant is None:
            raise KeyError(f"Variant not found: {variant_id}")
        if variant.status == VariantStatus.RETIRED:
            raise ValueError(f"Cannot evaluate retired variant: {variant_id}")

        await self._repo.update_status(variant_id, VariantStatus.EVALUATED)
        res = await self._repo.get_by_id(variant_id)
        if res is None:
            raise RuntimeError(f"Variant disappeared: {variant_id}")
        return res

    async def retire_variant(self, variant_id: str, *, reason: str | None = None) -> Variant:
        """Retire a variant."""
        variant = await self._repo.get_by_id(variant_id)
        if variant is None:
            raise KeyError(f"Variant not found: {variant_id}")

        await self._repo.update_status(variant_id, VariantStatus.RETIRED)
        res = await self._repo.get_by_id(variant_id)
        if res is None:
            raise RuntimeError(f"Variant disappeared: {variant_id}")
        return res


class EvolverModule(BaseModule):
    """Lifecycle and dependency injection module for the Evolver subsystem."""

    name = "evolver"
    version = "0.6.0"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._service: EvolverService | None = None

    async def _on_initialize(self) -> None:
        db = self.container.resolve(Database)
        # Ensure table exists
        try:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS evolver_variants (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    generation INTEGER NOT NULL DEFAULT 0,
                    parent_id TEXT,
                    payload TEXT NOT NULL,
                    mutation TEXT,
                    status TEXT NOT NULL DEFAULT 'candidate',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_evolver_status ON evolver_variants(status);
                CREATE INDEX IF NOT EXISTS idx_evolver_parent ON evolver_variants(parent_id);
                """
            )
        except Exception:
            log.exception("evolver.table_init_failed")

        repo = EvolverRepository(db)
        audit = self.container.resolve(AuditLogger)
        events = self.container.try_resolve(EventBus)

        proposer = ProposalService(repo, events)
        applier = ApplicationService(repo, audit, events)
        self._service = EvolverService(repo, proposer, applier, events)

        self.container.register_instance(EvolverRepository, repo)
        self.container.register_instance(ProposalService, proposer)
        self.container.register_instance(VariantProposer, proposer)
        self.container.register_instance(ApplicationService, applier)
        self.container.register_instance(VariantApplier, applier)
        self.container.register_instance(EvolverService, self._service)
        self.container.register_instance(Evolver, self._service)

    async def _on_health(self) -> HealthStatus | None:
        if self._service is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        return HealthStatus.healthy(self.name, "ok")

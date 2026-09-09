"""Interfaces for Evolver self-improvement subsystem."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from sage.evolver.models import MutationRecord, PromotionEvidence, Variant, VariantStatus


@runtime_checkable
class VariantProposer(Protocol):
    """Protocol for proposing new variants with zero side effects on running systems."""

    async def propose_variant(
        self,
        *,
        name: str,
        payload: str,
        parent_id: str | None = None,
        mutation: MutationRecord | str | None = None,
    ) -> Variant:
        """Create and persist a candidate variant proposal without activating it."""
        ...


@runtime_checkable
class VariantApplier(Protocol):
    """Protocol for safely activating a verified variant, strictly requiring approval."""

    async def apply_variant(
        self,
        variant_id: str,
        *,
        approved: bool,
        evidence: PromotionEvidence,
        approver: str = "system",
        reason: str | None = None,
    ) -> Variant:
        """Activate a candidate variant. Must fail if approved is False or evidence is invalid."""
        ...


@runtime_checkable
class Evolver(Protocol):
    """Full evolver interface for variant lifecycle management."""

    async def get_variant(self, variant_id: str) -> Variant | None:
        ...

    async def get_active_variant(self) -> Variant | None:
        ...

    async def list_variants(
        self,
        *,
        status: VariantStatus | None = None,
        limit: int = 50,
    ) -> list[Variant]:
        ...

    async def get_lineage(self, variant_id: str) -> list[Variant]:
        ...

    async def mark_evaluated(self, variant_id: str) -> Variant:
        ...

    async def retire_variant(self, variant_id: str, *, reason: str | None = None) -> Variant:
        ...

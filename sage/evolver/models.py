"""Models for Evolver variant iteration and lineage tracking."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso


class VariantStatus(str, Enum):
    CANDIDATE = "candidate"
    EVALUATED = "evaluated"
    PROMOTED = "promoted"
    RETIRED = "retired"
    ACTIVE = "active"


class MutationRecord(BaseModel):
    """Immutable record describing a single mutation step."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: new_id("mut"))
    description: str
    target: str = "system_prompt"
    diff_summary: str | None = None
    created_at: str = Field(default_factory=utcnow_iso)


class PromotionEvidence(BaseModel):
    """Evidence required to validate and promote a candidate variant."""

    run_id: str
    mean_score: float
    baseline_mean_score: float
    cases_won: int = 0
    cases_lost: int = 0
    cases_tied: int = 0
    summary: str | None = None


class Variant(BaseModel):
    """A self-improvement variant entity with lineage tracking."""

    id: str = Field(default_factory=lambda: new_id("var"))
    name: str
    generation: int = 0
    parent_id: str | None = None
    payload: str
    mutation: str | None = None
    status: VariantStatus = VariantStatus.CANDIDATE
    created_at: str = Field(default_factory=utcnow_iso)
    updated_at: str = Field(default_factory=utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "generation": self.generation,
            "parent_id": self.parent_id,
            "payload": self.payload,
            "mutation": self.mutation,
            "status": self.status.value if isinstance(self.status, VariantStatus) else self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

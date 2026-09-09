"""Models for SOUP (Small Offline Uniform Probe) experiment comparison."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso


class EvalCase(BaseModel):
    """A single test case for offline evaluation."""

    id: str
    input: str
    expected: str | None = None


class SoupTrialResult(BaseModel):
    """Per-case scoring result for one variant."""

    case_id: str
    score: int  # 0-100
    response: str


class SoupRankingEntry(BaseModel):
    """Aggregate scoring for one variant across all cases."""

    variant_id: str
    name: str
    is_baseline: bool
    mean_score: float
    per_case: list[SoupTrialResult]


class SoupReport(BaseModel):
    """Complete SOUP run report with winner determination."""

    run_id: str
    baseline_variant_id: str
    winner_variant_id: str | None
    ranking: list[SoupRankingEntry]
    margin: float | None


class SoupRun(BaseModel):
    """Persistent record of a SOUP experiment comparison."""

    id: str = Field(default_factory=lambda: new_id("soup"))
    name: str
    eval_set_name: str = "builtin"
    baseline_variant_id: str
    winner_variant_id: str | None = None
    status: str = "completed"
    created_at: str = Field(default_factory=utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "eval_set_name": self.eval_set_name,
            "baseline_variant_id": self.baseline_variant_id,
            "winner_variant_id": self.winner_variant_id,
            "status": self.status,
            "created_at": self.created_at,
        }


class SoupTrial(BaseModel):
    """Individual trial record: one variant on one case."""

    id: str = Field(default_factory=lambda: new_id("trial"))
    run_id: str
    variant_id: str
    case_id: str
    score: int  # 0-100
    response: str
    created_at: str = Field(default_factory=utcnow_iso)

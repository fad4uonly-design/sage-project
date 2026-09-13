"""Decision traces — the NNsight-style introspection contract for Evolver/SOUP.

Model-level inspection (architecture, weights) lives in the MIE inspectors.
This module defines the *decision-level* trace format shared with the SAGE
TypeScript layer (``src/sage/introspect.ts``): when the Evolver prefers a
variant, the decision is decomposed into per-case evidence so it can be
audited instead of trusted as a black box.

Pure data + validation; no evaluation logic lives here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CaseTrace:
    """Per-eval-case margin between the winning variant and the baseline."""

    case_id: str
    winner_score: float | None
    baseline_score: float
    margin: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "winner_score": self.winner_score,
            "baseline_score": self.baseline_score,
            "margin": self.margin,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CaseTrace":
        winner = data.get("winner_score")
        return cls(
            case_id=str(data["case_id"]),
            winner_score=None if winner is None else float(winner),
            baseline_score=float(data["baseline_score"]),
            margin=float(data["margin"]),
        )


@dataclass(frozen=True)
class DecisionTraceStats:
    """Aggregate shape of a decision: wins, losses, ties, margin spread."""

    cases_won: int
    cases_lost: int
    cases_tied: int
    mean_margin: float
    max_margin: float
    margin_std_dev: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "cases_won": self.cases_won,
            "cases_lost": self.cases_lost,
            "cases_tied": self.cases_tied,
            "mean_margin": self.mean_margin,
            "max_margin": self.max_margin,
            "margin_std_dev": self.margin_std_dev,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DecisionTraceStats":
        return cls(
            cases_won=int(data["cases_won"]),
            cases_lost=int(data["cases_lost"]),
            cases_tied=int(data["cases_tied"]),
            mean_margin=float(data["mean_margin"]),
            max_margin=float(data["max_margin"]),
            margin_std_dev=float(data["margin_std_dev"]),
        )


@dataclass(frozen=True)
class DecisionTrace:
    """A full, auditable record of one variant-selection decision."""

    run_id: int
    run_name: str
    eval_set_name: str
    winner_variant_id: int | None
    winner_name: str | None
    baseline_name: str
    winner_mean_score: float | None
    baseline_mean_score: float
    per_case: tuple[CaseTrace, ...] = field(default_factory=tuple)
    stats: DecisionTraceStats | None = None
    explanation: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_name": self.run_name,
            "eval_set_name": self.eval_set_name,
            "winner_variant_id": self.winner_variant_id,
            "winner_name": self.winner_name,
            "baseline_name": self.baseline_name,
            "winner_mean_score": self.winner_mean_score,
            "baseline_mean_score": self.baseline_mean_score,
            "per_case": [c.to_dict() for c in self.per_case],
            "stats": self.stats.to_dict() if self.stats else None,
            "explanation": list(self.explanation),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DecisionTrace":
        stats_raw = data.get("stats")
        return cls(
            run_id=int(data["run_id"]),
            run_name=str(data["run_name"]),
            eval_set_name=str(data["eval_set_name"]),
            winner_variant_id=(
                None
                if data.get("winner_variant_id") is None
                else int(data["winner_variant_id"])
            ),
            winner_name=(
                None
                if data.get("winner_name") is None
                else str(data["winner_name"])
            ),
            baseline_name=str(data["baseline_name"]),
            winner_mean_score=(
                None
                if data.get("winner_mean_score") is None
                else float(data["winner_mean_score"])
            ),
            baseline_mean_score=float(data["baseline_mean_score"]),
            per_case=tuple(CaseTrace.from_dict(c) for c in data.get("per_case", [])),
            stats=(
                None
                if stats_raw is None
                else DecisionTraceStats.from_dict(stats_raw)
            ),
            explanation=tuple(str(item) for item in data.get("explanation", [])),
        )


def summarize_decision(trace: DecisionTrace) -> str:
    """One-line, human-readable summary of the decision (for logs/reports)."""
    if trace.winner_variant_id is None or trace.winner_name is None:
        return (
            f"run #{trace.run_id}: no challenger beat baseline "
            f"{trace.baseline_name!r}"
        )
    winner_score = (
        f"{trace.winner_mean_score:.2f}"
        if trace.winner_mean_score is not None
        else "n/a"
    )
    return (
        f"run #{trace.run_id}: {trace.winner_name!r} beat baseline "
        f"{trace.baseline_name!r} ({winner_score} vs "
        f"{trace.baseline_mean_score:.2f})"
    )

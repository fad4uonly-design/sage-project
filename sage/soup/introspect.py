"""NNsight-style introspection for SOUP experiment runs."""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, Field

from sage.soup.models import SoupReport


class CaseTrace(BaseModel):
    """Per-case trace comparing winner against baseline."""

    case_id: str
    winner_score: int | None
    baseline_score: int
    margin: float
    winner_response: str | None
    baseline_response: str


class DecisionStats(BaseModel):
    """Statistical summary of per-case performance margins."""

    cases_won: int = 0
    cases_lost: int = 0
    cases_tied: int = 0
    mean_margin: float = 0.0
    max_margin: float = 0.0
    margin_std_dev: float = 0.0


class DecisionTrace(BaseModel):
    """Full explainable decision trace for a SOUP run."""

    run_id: str
    run_name: str
    eval_set_name: str
    winner_variant_id: str | None
    winner_name: str | None
    baseline_name: str
    winner_mean_score: float | None
    baseline_mean_score: float
    per_case: list[CaseTrace]
    stats: DecisionStats
    explanation: list[str]


def mean(values: list[float | int]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def std_dev(values: list[float | int]) -> float:
    if not values:
        return 0.0
    mu = mean(values)
    variance = sum((v - mu) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def build_decision_trace_from_report(
    report: SoupReport,
    run_name: str,
    eval_set_name: str,
) -> DecisionTrace:
    """Build a decision trace directly from a SoupReport object."""
    baseline_entry = next(
        (r for r in report.ranking if r.variant_id == report.baseline_variant_id),
        report.ranking[0],
    )
    baseline_name = baseline_entry.name
    baseline_mean = baseline_entry.mean_score

    winner_entry = next(
        (r for r in report.ranking if r.variant_id == report.winner_variant_id),
        None,
    )
    winner_name = winner_entry.name if winner_entry else None
    winner_mean = winner_entry.mean_score if winner_entry else None

    # Get sorted list of case IDs
    case_ids = sorted({c.case_id for r in report.ranking for c in r.per_case})

    per_case: list[CaseTrace] = []
    for case_id in case_ids:
        b_case = next((c for c in baseline_entry.per_case if c.case_id == case_id), None)
        b_score = b_case.score if b_case else 0
        b_resp = b_case.response if b_case else ""

        w_case = next((c for c in winner_entry.per_case if c.case_id == case_id), None) if winner_entry else None
        w_score = w_case.score if w_case else None
        w_resp = w_case.response if w_case else None

        margin = round((w_score - b_score), 2) if w_score is not None else 0.0

        per_case.append(
            CaseTrace(
                case_id=case_id,
                winner_score=w_score,
                baseline_score=b_score,
                margin=margin,
                winner_response=w_resp,
                baseline_response=b_resp,
            )
        )

    margins = [c.margin for c in per_case]
    stats = DecisionStats(
        cases_won=sum(1 for c in per_case if c.margin > 0),
        cases_lost=sum(1 for c in per_case if c.margin < 0),
        cases_tied=sum(1 for c in per_case if c.margin == 0),
        mean_margin=round(mean(margins), 2),
        max_margin=max(margins) if margins else 0.0,
        margin_std_dev=round(std_dev(margins), 2),
    )

    explanation: list[str] = [
        f"Run #{report.run_id} \"{run_name}\" evaluated {len(case_ids)} case(s) on the \"{eval_set_name}\" eval set.",
        f"Baseline: {baseline_name} (mean {baseline_mean:.2f}).",
    ]

    if report.winner_variant_id is None or winner_name is None or winner_mean is None:
        explanation.append("Decision: no challenger beat the baseline, so no variant was selected.")
    else:
        explanation.append(
            f"Winner: {winner_name} (mean {winner_mean:.2f}), a margin of {stats.mean_margin:.2f} points over the baseline."
        )
        explanation.append(
            f"Per-case record: won {stats.cases_won}, lost {stats.cases_lost}, tied {stats.cases_tied} of {len(case_ids)}."
        )
        variance_note = (
            "high variance, the win is uneven across cases."
            if stats.margin_std_dev > 15
            else "the win is reasonably consistent across cases."
        )
        explanation.append(
            f"Margin spread: best case +{stats.max_margin:.2f}, standard deviation {stats.margin_std_dev:.2f} — {variance_note}"
        )

        biggest = max(per_case, key=lambda c: c.margin) if per_case else None
        if biggest and biggest.margin > 0:
            explanation.append(f"Biggest contribution: case \"{biggest.case_id}\" (+{biggest.margin:.2f}).")

    explanation.append(
        "Decision policy: promotion requires a strict mean-score win over the baseline plus an explicit human approval (see Evolver.apply_variant)."
    )

    return DecisionTrace(
        run_id=report.run_id,
        run_name=run_name,
        eval_set_name=eval_set_name,
        winner_variant_id=report.winner_variant_id,
        winner_name=winner_name,
        baseline_name=baseline_name,
        winner_mean_score=winner_mean,
        baseline_mean_score=baseline_mean,
        per_case=per_case,
        stats=stats,
        explanation=explanation,
    )


def explain_trace(trace: DecisionTrace) -> str:
    """Format decision trace explanation as a numbered list."""
    return "\n".join(f"{i + 1}. {line}" for i, line in enumerate(trace.explanation))

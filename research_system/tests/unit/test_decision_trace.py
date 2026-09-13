"""Tests for the decision-trace contract (shared with the TS introspect layer)."""

from __future__ import annotations

import pytest

from sage_research.experiments.decision_trace import (
    CaseTrace,
    DecisionTrace,
    DecisionTraceStats,
    summarize_decision,
)


def _trace(**overrides) -> DecisionTrace:  # noqa: ANN003
    base = dict(
        run_id=7,
        run_name="prompt-variant-comparison",
        eval_set_name="tinystories-builtin",
        winner_variant_id=3,
        winner_name="baseline-iter",
        baseline_name="baseline",
        winner_mean_score=81.5,
        baseline_mean_score=70.0,
        per_case=(
            CaseTrace(case_id="ts-001", winner_score=90.0, baseline_score=60.0, margin=30.0),
            CaseTrace(case_id="ts-002", winner_score=80.0, baseline_score=80.0, margin=0.0),
            CaseTrace(case_id="ts-003", winner_score=74.5, baseline_score=70.0, margin=4.5),
        ),
        stats=DecisionTraceStats(
            cases_won=2,
            cases_lost=0,
            cases_tied=1,
            mean_margin=11.5,
            max_margin=30.0,
            margin_std_dev=13.2,
        ),
        explanation=("run evaluated 3 cases", "winner mean 81.50"),
    )
    base.update(overrides)
    return DecisionTrace(**base)


def test_round_trip_preserves_all_fields() -> None:
    trace = _trace()
    data = trace.to_dict()
    restored = DecisionTrace.from_dict(data)
    assert restored == trace


def test_none_winner_survives_round_trip() -> None:
    trace = _trace(
        winner_variant_id=None,
        winner_name=None,
        winner_mean_score=None,
    )
    restored = DecisionTrace.from_dict(trace.to_dict())
    assert restored.winner_variant_id is None
    assert restored.winner_mean_score is None
    assert summarize_decision(restored).endswith("no challenger beat baseline 'baseline'")


def test_summarize_decision_mentions_winner_and_margin() -> None:
    summary = summarize_decision(_trace())
    assert "baseline-iter" in summary
    assert "81.50 vs 70.00" in summary


def test_stats_carry_the_spread() -> None:
    trace = _trace()
    assert trace.stats is not None
    assert trace.stats.max_margin == 30.0
    assert trace.stats.margin_std_dev > 0


def test_case_trace_requires_case_id() -> None:
    with pytest.raises(KeyError):
        CaseTrace.from_dict({"baseline_score": 1.0, "margin": 0.0})

"""Interfaces for SOUP evaluation subsystem."""

from __future__ import annotations

from typing import Any, Callable, Coroutine, Protocol, runtime_checkable

from sage.soup.introspect import DecisionTrace
from sage.soup.models import EvalCase, SoupReport, SoupRun, SoupTrial
from sage.soup.scorer import CaseScorer

# Async or sync variant runner: (payload, input) -> response
VariantRunner = Callable[[str, str], Coroutine[Any, Any, str] | str]


@runtime_checkable
class SoupEngine(Protocol):
    """Protocol for running and querying SOUP experiment comparisons."""

    async def run_comparison(
        self,
        *,
        name: str,
        variant_ids: list[str],
        eval_set: list[EvalCase],
        runner: VariantRunner | None = None,
        scorer: CaseScorer | None = None,
        eval_set_name: str = "builtin",
    ) -> SoupReport:
        """Run an offline comparison across multiple candidate variants."""
        ...

    async def get_run(self, run_id: str) -> SoupRun | None:
        """Fetch metadata for a SOUP run."""
        ...

    async def get_trials(self, run_id: str) -> list[SoupTrial]:
        """Fetch all trials for a SOUP run."""
        ...

    async def get_decision_trace(self, run_id: str) -> DecisionTrace:
        """Generate an explainable decision trace for a SOUP run."""
        ...

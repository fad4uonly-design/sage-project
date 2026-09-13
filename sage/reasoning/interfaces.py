"""Reasoning engine protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from sage.reasoning.models import ReasoningContext, ReasoningResult, StrategyKind


@runtime_checkable
class ReasoningEngine(Protocol):
    async def reason(
        self,
        problem: str,
        *,
        context: ReasoningContext | None = None,
        strategy: StrategyKind = StrategyKind.AUTO,
        use_retrieval: bool = True,
        combine_top_k: int = 1,
    ) -> ReasoningResult: ...

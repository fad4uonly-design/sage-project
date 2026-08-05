"""Strategy protocol and registry."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from sage.logging import get_logger
from sage.reasoning.models import ReasoningContext, ReasoningResult, StrategyKind

log = get_logger(__name__)


@runtime_checkable
class ReasoningStrategy(Protocol):
    @property
    def kind(self) -> StrategyKind: ...

    @property
    def name(self) -> str: ...

    @property
    def domains(self) -> frozenset[str]: ...

    def suitability(self, problem: str, context: ReasoningContext) -> float:
        """Return 0..1 confidence that this strategy fits the problem."""
        ...

    async def apply(
        self,
        problem: str,
        context: ReasoningContext,
        *,
        models: Any | None = None,
    ) -> ReasoningResult: ...


class StrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, ReasoningStrategy] = {}

    def register(self, strategy: ReasoningStrategy) -> None:
        self._strategies[strategy.kind.value] = strategy
        log.debug("reasoning.strategy_registered", kind=strategy.kind.value, name=strategy.name)

    def get(self, kind: StrategyKind | str) -> ReasoningStrategy | None:
        key = kind.value if isinstance(kind, StrategyKind) else kind
        return self._strategies.get(key)

    def all(self) -> list[ReasoningStrategy]:
        return list(self._strategies.values())

    def select(
        self,
        problem: str,
        context: ReasoningContext,
        *,
        preferred: StrategyKind | None = None,
        top_k: int = 1,
    ) -> list[ReasoningStrategy]:
        if preferred and preferred != StrategyKind.AUTO:
            s = self.get(preferred)
            if s:
                return [s]
        scored: list[tuple[float, ReasoningStrategy]] = []
        for s in self._strategies.values():
            score = s.suitability(problem, context)
            scored.append((score, s))
        scored.sort(key=lambda x: x[0], reverse=True)
        # Always return at least top_k (fallback strategies have low but non-zero base)
        return [s for _, s in scored[:top_k]]

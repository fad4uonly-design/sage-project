"""Learning engine protocol."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from sage.learning.models import Feedback, Observation, Preference


@runtime_checkable
class LearningEngine(Protocol):
    async def observe(self, observation: Observation) -> None: ...

    async def learn_preference(
        self, key: str, value: Any, *, confidence: float = 0.5, source: str = "learned"
    ) -> None: ...

    async def get_preference(self, key: str) -> Preference | None: ...

    async def refine(self, feedback: Feedback) -> None: ...

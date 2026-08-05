"""Orchestrator protocol."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from sage.orchestrator.models import Intent, OrchestratorResult


@runtime_checkable
class Orchestrator(Protocol):
    async def analyze_intent(self, message: str, *, context: dict[str, Any] | None = None) -> Intent: ...

    async def handle(
        self,
        message: str,
        *,
        session_id: str | None = None,
        user_id: str = "default",
        context: dict[str, Any] | None = None,
    ) -> OrchestratorResult: ...

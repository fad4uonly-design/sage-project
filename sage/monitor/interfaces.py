"""Health monitor protocol."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from sage.core.health import SystemHealth


@runtime_checkable
class HealthMonitor(Protocol):
    async def snapshot(self) -> dict[str, Any]: ...

    async def probe(self) -> SystemHealth: ...

    async def record_snapshot(self) -> dict[str, Any]: ...

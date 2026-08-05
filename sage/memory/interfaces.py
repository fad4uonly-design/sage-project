"""Memory system protocols."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from sage.memory.models import ConsolidationReport, MemoryItem, MemoryType


@runtime_checkable
class MemorySystem(Protocol):
    async def store(self, item: MemoryItem) -> str: ...

    async def recall(
        self,
        query: str,
        *,
        limit: int = 10,
        types: Sequence[MemoryType] | None = None,
    ) -> list[MemoryItem]: ...

    async def get(self, memory_id: str) -> MemoryItem | None: ...

    async def update(self, memory_id: str, **fields: Any) -> MemoryItem: ...

    async def forget(self, memory_id: str, *, reason: str = "") -> bool: ...

    async def consolidate(self) -> ConsolidationReport: ...

    async def count(self, *, include_deleted: bool = False) -> int: ...

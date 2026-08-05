"""Memory system tests."""

from __future__ import annotations

import pytest

from sage.core.engine import SageEngine
from sage.memory.interfaces import MemorySystem
from sage.memory.models import MemoryItem, MemoryType


@pytest.mark.asyncio
async def test_store_and_recall(engine: SageEngine) -> None:
    mem = engine.container.resolve(MemorySystem)  # type: ignore[type-abstract]
    await mem.store(
        MemoryItem(
            type=MemoryType.FACT,
            content="User grows tomatoes in greenhouse A",
            importance=0.9,
            tags=["agriculture", "tomatoes"],
        )
    )
    results = await mem.recall("tomatoes")
    assert any("tomatoes" in r.content.lower() for r in results)


@pytest.mark.asyncio
async def test_forget(engine: SageEngine) -> None:
    mem = engine.container.resolve(MemorySystem)  # type: ignore[type-abstract]
    mid = await mem.store(
        MemoryItem(type=MemoryType.FACT, content="Temporary secret note XYZ")
    )
    assert await mem.get(mid) is not None
    assert await mem.forget(mid, reason="test") is True
    assert await mem.get(mid) is None


@pytest.mark.asyncio
async def test_consolidate_expires_short_term(engine: SageEngine) -> None:
    mem = engine.container.resolve(MemorySystem)  # type: ignore[type-abstract]
    await mem.store(
        MemoryItem(
            type=MemoryType.SHORT_TERM,
            content="ephemeral thought",
            expires_at="2000-01-01T00:00:00Z",
        )
    )
    report = await mem.consolidate()
    assert report.expired >= 1

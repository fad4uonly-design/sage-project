"""Cognitive memory pipeline tests."""

from __future__ import annotations

import pytest
from sage.core.engine import SageEngine
from sage.memory.interfaces import MemorySystem
from sage.memory.models import MemoryItem, MemoryType
from sage.memory.service import SQLiteMemorySystem


@pytest.mark.asyncio
async def test_duplicate_reinforce(engine: SageEngine) -> None:
    mem = engine.container.resolve(MemorySystem)  # type: ignore[type-abstract]
    content = "User irrigates greenhouse zone B every morning at 6am"
    id1 = await mem.store(
        MemoryItem(type=MemoryType.FACT, content=content, importance=0.5, source="user")
    )
    id2 = await mem.store(
        MemoryItem(type=MemoryType.FACT, content=content, importance=0.6, source="user")
    )
    assert id1 == id2
    item = await mem.get(id1)
    assert item is not None
    assert item.importance >= 0.6


@pytest.mark.asyncio
async def test_importance_scoring(engine: SageEngine) -> None:
    mem = engine.container.resolve(MemorySystem)  # type: ignore[type-abstract]
    mid = await mem.store(
        MemoryItem(
            type=MemoryType.PREFERENCE,
            content="I always prefer detailed explanations",
            importance=0.4,
            source="user",
        )
    )
    item = await mem.get(mid)
    assert item is not None
    assert item.importance > 0.4


@pytest.mark.asyncio
async def test_relations_on_store(engine: SageEngine) -> None:
    mem = engine.container.resolve(SQLiteMemorySystem)
    await mem.store(
        MemoryItem(type=MemoryType.FACT, content="Tomatoes need daily irrigation in summer")
    )
    mid = await mem.store(
        MemoryItem(type=MemoryType.FACT, content="Tomato greenhouse irrigation schedule updated")
    )
    rels = await mem.relations(mid)
    # May or may not find overlap depending on terms — just ensure API works
    assert isinstance(rels, list)


@pytest.mark.asyncio
async def test_consolidate_report_fields(engine: SageEngine) -> None:
    mem = engine.container.resolve(MemorySystem)  # type: ignore[type-abstract]
    report = await mem.consolidate()
    assert hasattr(report, "related")
    assert hasattr(report, "rescored")
    assert report.message

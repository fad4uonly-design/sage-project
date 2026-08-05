"""Layered retrieval tests."""

from __future__ import annotations

import pytest

from sage.core.engine import SageEngine
from sage.memory.interfaces import MemorySystem
from sage.memory.models import MemoryItem, MemoryType
from sage.retrieval.interfaces import Retriever
from sage.retrieval.models import RetrievalLayer


@pytest.mark.asyncio
async def test_layered_retrieve(engine: SageEngine) -> None:
    mem = engine.container.resolve(MemorySystem)  # type: ignore[type-abstract]
    await mem.store(
        MemoryItem(
            type=MemoryType.FACT,
            content="User irrigates tomatoes every morning",
            importance=0.8,
            source="test",
        )
    )
    retriever = engine.container.resolve(Retriever)  # type: ignore[type-abstract]
    result = await retriever.retrieve("tomatoes irrigation", limit=10)
    assert result.ranked
    assert result.overall_confidence > 0
    layers = {i.layer for i in result.items}
    # At least memory or graph from seed ontology
    assert layers & {
        RetrievalLayer.MEMORY,
        RetrievalLayer.KNOWLEDGE_GRAPH,
        RetrievalLayer.SEMANTIC,
    }
    assert result.explanation

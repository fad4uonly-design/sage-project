"""Layered retrieval tests."""

from __future__ import annotations

from pathlib import Path

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


# -- Regression: semantic relevance must survive into the MEMORY layer --------


async def test_memory_layer_preserves_semantic_relevance_over_importance(
    engine: SageEngine, tmp_path: Path
) -> None:
    """'What do you remember about the sky?' must rank the sky fact above a
    high-importance, freshly-written unrelated memory.

    The MEMORY layer used to build EvidenceItem(score=importance), letting an
    unrelated but important memory outrank the semantically relevant one. The
    memory system now carries the semantic/lexical relevance per hit and the
    layer ranks on it; importance is secondary/informational only.
    """
    from sage.config.settings import Settings
    from sage.core.container import Container
    from sage.db.connection import Database
    from sage.db.migrations import apply_migrations
    from sage.events.bus import InMemoryEventBus
    from sage.memory.cognitive import CognitiveMemorySupport
    from sage.memory.index import SqliteVectorIndex
    from sage.memory.service import SQLiteMemorySystem
    from sage.memory.store import MemoryStore
    from sage.models.local_embedding import HashingEmbeddingModel
    from sage.retrieval.pipeline import LayeredRetriever

    settings = Settings(
        env="test",
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "retrieval.db",
        logging={"level": "WARNING", "format": "console"},
        scheduler={"enabled": False},
        plugins={"enabled": False, "auto_load": False},
    )
    settings.ensure_directories()
    db = Database(settings.db_path)
    await db.open()
    try:
        await apply_migrations(db)
        cognitive = CognitiveMemorySupport(db)
        await cognitive.ensure_content_hash_column()
        embedding = HashingEmbeddingModel(dim=128)
        index = SqliteVectorIndex(db)
        await index.ensure_table()
        index.attach(embedding)

        class _HashRouter:
            """Minimal router double exposing the hashing embedding."""

            def get_embedding_model(self) -> HashingEmbeddingModel:
                return embedding

        mem = SQLiteMemorySystem(
            MemoryStore(db),
            cognitive,
            InMemoryEventBus(),
            settings,
            index=index,
            # Production wiring (MemoryModule passes the same resolver) —
            # without it the system never attaches/uses the index.
            router_resolver=lambda: _HashRouter(),
        )

        # Pins ranking, not the production floor: the hashing embedder cannot
        # reach nomic-scale cosines for the sky fact.
        mem.MIN_RECALL_RELEVANCE = 0.0

        # Unrelated, but maximally important and freshly written. Shares NO
        # query tokens (not even "the") so the deterministic hashing embedding
        # gives it no relevance advantage; in production the real embedding
        # model (nomic-embed-text) provides the same separation semantically.
        await mem.store(
            MemoryItem(
                type=MemoryType.FACT,
                content="Irrigate tomato fields at dawn and dusk.",
                importance=1.0,
                source="test",
            )
        )
        # Semantically relevant, but low importance.
        await mem.store(
            MemoryItem(
                type=MemoryType.FACT,
                content="The sky is blue.",
                importance=0.1,
                source="test",
            )
        )

        container = Container()
        container.register_instance(MemorySystem, mem)
        retriever = LayeredRetriever(container)

        result = await retriever.retrieve(
            "What do you remember about the sky?", limit=10
        )

        memory_items = [i for i in result.ranked if i.layer == RetrievalLayer.MEMORY]
        assert memory_items, "expected memory evidence"
        top = memory_items[0]
        assert "sky" in top.content.lower()

        # The carried semantic relevance IS the score now.
        assert top.score == pytest.approx(top.metadata["relevance"])
        assert top.score > 0.0

        # The high-importance unrelated memory must not outrank the sky fact.
        agri = [i for i in memory_items if "tomato" in i.content.lower()]
        if agri:
            assert memory_items.index(top) < memory_items.index(agri[0])

        # No competing semantic layer duplicates when scored recall exists.
        assert all(i.layer != RetrievalLayer.SEMANTIC for i in result.items)
    finally:
        await db.close()


async def test_retrieval_still_ranks_relevant_memories(engine: SageEngine) -> None:
    """Existing behavior intact: a clearly relevant memory is retrieved."""
    mem = engine.container.resolve(MemorySystem)  # type: ignore[type-abstract]
    await mem.store(
        MemoryItem(
            type=MemoryType.FACT,
            content="The user waters orchids every Friday evening.",
            source="test",
        )
    )
    retriever = engine.container.resolve(Retriever)  # type: ignore[type-abstract]
    result = await retriever.retrieve("orchid watering schedule", limit=10)
    assert result.ranked
    contents = " ".join(i.content.lower() for i in result.ranked)
    assert "orchid" in contents

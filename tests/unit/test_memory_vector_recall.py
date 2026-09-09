"""Blended vector recall tests for the cognitive memory system."""

from __future__ import annotations

from pathlib import Path

from sage.config.settings import Settings
from sage.db.connection import Database
from sage.db.migrations import apply_migrations
from sage.events.bus import InMemoryEventBus
from sage.memory.cognitive import CognitiveMemorySupport
from sage.memory.index import SqliteVectorIndex
from sage.memory.models import MemoryItem, MemoryType
from sage.memory.service import SQLiteMemorySystem
from sage.memory.store import MemoryStore
from sage.models.local_embedding import HashingEmbeddingModel


def make_settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"

    return Settings(
        env="test",
        data_dir=data,
        db_path=data / "recall.db",
        logging={"level": "WARNING", "format": "console"},
        scheduler={"enabled": False},
        plugins={"enabled": False, "auto_load": False},
    )


async def _make_system(
    tmp_path: Path, *, with_index: bool = True
) -> tuple[SQLiteMemorySystem, Database]:
    settings = make_settings(tmp_path)
    db = Database(settings.db_path)
    await db.open()
    await apply_migrations(db)

    # The real MemoryModule runs this migration before the system is used.
    cognitive = CognitiveMemorySupport(db)
    await cognitive.ensure_content_hash_column()

    index: SqliteVectorIndex | None = None
    if with_index:
        index = SqliteVectorIndex(db)
        await index.ensure_table()
        index.attach(HashingEmbeddingModel(dim=128))

    system = SQLiteMemorySystem(
        MemoryStore(db),
        cognitive,
        InMemoryEventBus(),
        settings,
        index=index,
    )
    return system, db


async def test_stored_memory_found_by_vector_recall(tmp_path: Path) -> None:
    system, db = await _make_system(tmp_path)
    try:
        await system.store(
            MemoryItem(
                type=MemoryType.FACT,
                content="The greenhouse tomato sales doubled this summer.",
                source="user",
            )
        )
        await system.store(
            MemoryItem(
                type=MemoryType.FACT,
                content="Booked a flight to Tokyo for next Monday.",
            )
        )

        hits = await system.recall("tomato greenhouse sales", limit=2)

        assert hits, "expected recall results"
        assert "tomato" in hits[0].content.lower()

        # Access bookkeeping is persisted; returned objects are pre-update snapshots.
        for hit in hits:
            fresh = await system.get(hit.id)
            assert fresh is not None
            assert (fresh.access_count or 0) >= 1
            assert fresh.last_accessed_at is not None
    finally:
        await db.close()


async def test_recall_without_index_still_works(tmp_path: Path) -> None:
    system, db = await _make_system(tmp_path, with_index=False)
    try:
        memory_id = await system.store(
            MemoryItem(type=MemoryType.FACT, content="Plain keyword memory about cats.")
        )

        hits = await system.recall("cats", limit=5)

        assert [item.id for item in hits] == [memory_id]
    finally:
        await db.close()


async def test_vector_recall_surfaces_nonkeyword_match(tmp_path: Path) -> None:
    system, db = await _make_system(tmp_path)
    try:
        await system.store(
            MemoryItem(
                type=MemoryType.FACT,
                content="User prefers early morning walks before breakfast.",
            )
        )
        await system.store(
            MemoryItem(
                type=MemoryType.FACT,
                content="Meeting notes: quarterly budget review scheduled.",
            )
        )

        # No keyword overlap with the walks memory beyond "s"/"the" stoppers —
        # the vector path should still surface it among candidates.
        hits = await system.recall("morning routine walking habit", limit=5)

        assert hits, "expected recall results"
        contents = " ".join(item.content.lower() for item in hits)
        assert "morning walks" in contents
    finally:
        await db.close()

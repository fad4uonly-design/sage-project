"""Unit tests for the Lean Intelligence MemoryInterface adapter.

These tests exercise the adapter against the REAL memory stack —
SQLiteMemorySystem + SqliteVectorIndex with the offline HashingEmbeddingModel —
and must never require touching Phase 1 memory code.

Threshold context (hashing-space cosine bands, measured on this stack):
exact repeat ~0.87, contraction rewording ~0.64, same-topic-different-question
~0.25, unrelated ~-0.06-0.14. Default lookup threshold is 0.60.
"""

from __future__ import annotations

from pathlib import Path

from sage.config.settings import Settings
from sage.db.connection import Database
from sage.db.migrations import apply_migrations
from sage.events.bus import InMemoryEventBus
from sage.memory.cognitive import CognitiveMemorySupport
from sage.memory.index import SqliteVectorIndex
from sage.memory.memory_interface import MemoryHit, MemoryInterface
from sage.memory.service import SQLiteMemorySystem
from sage.memory.store import MemoryStore
from sage.models.local_embedding import HashingEmbeddingModel

QUESTION = "What is the capital of France?"
ANSWER = "Paris."
# Reworded on purpose: same question, different string (measured cosine
# ~0.64 in hashing space) — an exact-match implementation would return None
# here and fail this test.
REWORDING = "What's the capital of France?"
UNRELATED = "Schedule my dentist appointment for Tuesday morning"


def make_settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    return Settings(
        env="test",
        data_dir=data,
        db_path=data / "lean.db",
        logging={"level": "WARNING", "format": "console"},
        scheduler={"enabled": False},
        plugins={"enabled": False, "auto_load": False},
    )


async def make_stack(
    tmp_path: Path,
) -> tuple[MemoryInterface, SQLiteMemorySystem, SqliteVectorIndex, Database]:
    settings = make_settings(tmp_path)
    db = Database(settings.db_path)
    await db.open()
    await apply_migrations(db)

    # The real MemoryModule runs this migration before the system is used.
    cognitive = CognitiveMemorySupport(db)
    await cognitive.ensure_content_hash_column()

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
    return MemoryInterface(system, index), system, index, db


async def test_lookup_returns_none_on_empty_store(tmp_path: Path) -> None:
    iface, _system, _index, db = await make_stack(tmp_path)
    try:
        assert await iface.lookup(QUESTION) is None
    finally:
        await db.close()


async def test_write_then_lookup_exact_returns_high_confidence_hit(tmp_path: Path) -> None:
    iface, _system, _index, db = await make_stack(tmp_path)
    try:
        await iface.write(QUESTION, ANSWER)
        hit = await iface.lookup(QUESTION)

        assert hit is not None
        assert isinstance(hit, MemoryHit)
        assert hit.value == ANSWER
        assert hit.confidence >= 0.80  # measured ~0.87 in hashing space
        assert 0.0 <= hit.age_seconds < 60.0
    finally:
        await db.close()


async def test_lookup_uses_embedding_search_not_exact_match(tmp_path: Path) -> None:
    iface, _system, _index, db = await make_stack(tmp_path)
    try:
        await iface.write(QUESTION, ANSWER)
        hit = await iface.lookup(REWORDING)

        assert hit is not None, "reworded request must still match via embeddings"
        assert "Paris" in hit.value
        # Measured ~0.64: above the 0.60 lookup threshold, but clearly below
        # an exact repeat (~0.87) — proving a graded similarity search.
        assert hit.confidence >= 0.60
        assert hit.confidence < 0.87
    finally:
        await db.close()


async def test_lookup_unrelated_request_returns_none(tmp_path: Path) -> None:
    iface, _system, _index, db = await make_stack(tmp_path)
    try:
        await iface.write(QUESTION, ANSWER)
        # Measured cosine ~0.14 — far below the 0.60 threshold.
        assert await iface.lookup(UNRELATED) is None
    finally:
        await db.close()


async def test_has_similar_agrees_with_lookup(tmp_path: Path) -> None:
    iface, _system, _index, db = await make_stack(tmp_path)
    try:
        assert await iface.has_similar(QUESTION) is False  # empty store

        await iface.write(QUESTION, ANSWER)

        assert await iface.has_similar(REWORDING) is True
        assert await iface.has_similar(UNRELATED) is False
        assert (await iface.has_similar(QUESTION)) == (
            await iface.lookup(QUESTION) is not None
        )
    finally:
        await db.close()


async def test_write_persists_through_real_memory_system(tmp_path: Path) -> None:
    iface, system, index, db = await make_stack(tmp_path)
    try:
        await iface.write(QUESTION, ANSWER)

        # No parallel store: exactly one row in the real system, indexed.
        assert await system.count() == 1
        assert await index.count() == 1

        items = await system.recall("capital of France")
        assert items, "real memory system must be able to recall the write"
        stored = items[0]
        assert stored.summary == ANSWER
        assert stored.metadata["via"] == "memory_interface"
        assert stored.source == "lean_value_router"
    finally:
        await db.close()


async def test_duplicate_write_reinforces_instead_of_duplicating(tmp_path: Path) -> None:
    iface, system, index, db = await make_stack(tmp_path)
    try:
        await iface.write(QUESTION, ANSWER)
        await iface.write(QUESTION, ANSWER)  # identical -> content_hash pipeline

        assert await system.count() == 1
        assert await index.count() == 1
    finally:
        await db.close()


async def test_lookup_degrades_when_index_has_no_embedding(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    db = Database(settings.db_path)
    await db.open()
    await apply_migrations(db)
    cognitive = CognitiveMemorySupport(db)
    await cognitive.ensure_content_hash_column()
    bare_index = SqliteVectorIndex(db)  # deliberately never attached
    await bare_index.ensure_table()
    system = SQLiteMemorySystem(
        MemoryStore(db), cognitive, InMemoryEventBus(), settings, index=bare_index
    )
    iface = MemoryInterface(system, bare_index)
    try:
        await iface.write(QUESTION, ANSWER)  # persistence works regardless
        assert await iface.lookup(QUESTION) is None
        assert await iface.has_similar(QUESTION) is False
    finally:
        await db.close()


async def test_rejects_embedding_swap_that_would_orphan_vectors(tmp_path: Path) -> None:
    iface, system, index, db = await make_stack(tmp_path)
    try:
        wrong = HashingEmbeddingModel(dim=256)  # different tag than attached one
        try:
            MemoryInterface(system, index, embedding=wrong)
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for mismatched embedding")
    finally:
        await db.close()


async def test_flags_tag_drift_when_slot_repointed(tmp_path: Path) -> None:
    iface, _system, index, db = await make_stack(tmp_path)
    try:
        await iface.write(QUESTION, ANSWER)
        assert iface.tag_drifted is False

        # Simulate the memory system re-pointing the embedding slot to a
        # different model (what a mismatched router resolution would do).
        index.attach(HashingEmbeddingModel(dim=256))

        # Vectors keep their old model_tag -> not searchable under the new one.
        assert await iface.lookup(QUESTION) is None
        assert iface.tag_drifted is True
    finally:
        await db.close()

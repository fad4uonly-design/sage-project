"""Vector index tests (TurboVec concept: tag-aware, persisted cosine index)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sage.db.connection import Database
from sage.memory.index import SqliteVectorIndex
from sage.models.local_embedding import HashingEmbeddingModel


async def _make_index(db: Database, *, dim: int = 128) -> SqliteVectorIndex:
    index = SqliteVectorIndex(db)
    await index.ensure_table()
    index.attach(HashingEmbeddingModel(dim=dim))
    return index


async def test_search_ranks_related_memories_first(tmp_path: Path) -> None:
    db = Database(tmp_path / "vectors.db")
    await db.open()
    index = await _make_index(db)

    await index.upsert("m1", "greenhouse tomato sales doubled this summer")
    await index.upsert("m2", "flight booking to tokyo next monday")
    await index.upsert("m3", "tomato plants need weekly watering in the greenhouse")

    hits = await index.search("tomato greenhouse care", limit=2)

    assert hits, "expected at least one hit"
    assert hits[0][0] in {"m1", "m3"}
    assert all(0.0 <= score <= 1.0001 for _, score in hits)
    await db.close()


async def test_remove_drops_vector(tmp_path: Path) -> None:
    db = Database(tmp_path / "vectors.db")
    await db.open()
    index = await _make_index(db)

    await index.upsert("m1", "unique pineapple pizza opinion")
    assert await index.count() == 1

    await index.remove("m1")

    assert await index.count() == 0
    assert await index.search("pineapple", limit=5) == []
    await db.close()


async def test_rebuild_replaces_active_tag_rows(tmp_path: Path) -> None:
    db = Database(tmp_path / "vectors.db")
    await db.open()
    index = await _make_index(db)

    await index.upsert("m-old", "stale memory content")

    written = await index.rebuild(
        [("m2", "brand new content"), ("m3", "another fresh entry")]
    )

    assert written == 2
    assert await index.count() == 2
    ids = {memory_id for memory_id, _ in await index.search("content", limit=5)}
    assert ids <= {"m2", "m3"}
    await db.close()


async def test_tag_change_requires_rebuild(tmp_path: Path) -> None:
    db = Database(tmp_path / "vectors.db")
    await db.open()
    index = await _make_index(db, dim=128)

    await index.upsert("m1", "hello there")
    assert await index.count() == 1

    index.attach(HashingEmbeddingModel(dim=256))
    assert await index.count() == 0

    await index.rebuild([("m1", "hello there")])
    assert await index.count() == 1
    hits = await index.search("hello", limit=1)
    assert hits and hits[0][0] == "m1"
    await db.close()


async def test_vectors_persist_across_reopen(tmp_path: Path) -> None:
    path = tmp_path / "persist.db"

    db1 = Database(path)
    await db1.open()
    index1 = await _make_index(db1)
    await index1.upsert("m1", "lasting memory of sage")
    await db1.close()

    db2 = Database(path)
    await db2.open()
    index2 = await _make_index(db2)
    assert await index2.count() == 1
    hits = await index2.search("sage memory", limit=1)
    assert hits and hits[0][0] == "m1"
    await db2.close()


async def test_unattached_index_raises(tmp_path: Path) -> None:
    db = Database(tmp_path / "cold.db")
    await db.open()
    index = SqliteVectorIndex(db)
    await index.ensure_table()

    with pytest.raises(RuntimeError):
        await index.upsert("m1", "text")
    with pytest.raises(RuntimeError):
        await index.search("query")
    await db.close()

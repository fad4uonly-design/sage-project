"""DI tests for the EXISTING ``sage.memory.index.VectorIndex``.

These verify that bootstrap now exposes the real ``SqliteVectorIndex`` through
the container (lazy factory, singleton, embedding attached from the router) and
that a ``MemoryInterface`` can be built from the container-resolved index.
"""

from __future__ import annotations

from pathlib import Path

from sage.config.settings import Settings
from sage.core.bootstrap import Bootstrapper
from sage.core.container import Container
from sage.db.connection import Database
from sage.db.migrations import apply_migrations
from sage.events.bus import InMemoryEventBus
from sage.memory.cognitive import CognitiveMemorySupport
from sage.memory.index import VectorIndex, SqliteVectorIndex
from sage.memory.memory_interface import MemoryInterface
from sage.memory.service import SQLiteMemorySystem
from sage.memory.store import MemoryStore
from sage.models.interfaces import ModelRouter
from sage.models.local_embedding import HashingEmbeddingModel

QUESTION = "What is the capital of France?"
ANSWER = "Paris."


def make_settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    return Settings(
        env="test",
        data_dir=data,
        db_path=data / "vec.db",
        logging={"level": "WARNING", "format": "console"},  # type: ignore[arg-type]
        scheduler={"enabled": False},  # type: ignore[arg-type]
        plugins={"enabled": False, "auto_load": False},  # type: ignore[arg-type]
    )


def make_bootstrapper(settings: Settings) -> Bootstrapper:
    settings.ensure_directories()
    bt = Bootstrapper(settings)
    bt._register_infrastructure()
    return bt


class _RouterWithEmbedding:
    def __init__(self, embedding: HashingEmbeddingModel) -> None:
        self._emb = embedding

    def get_language_model(self, *, capability: str | None = None):
        return None

    def get_embedding_model(self):
        return self._emb


class _RouterWithoutEmbedding:
    def get_language_model(self, *, capability: str | None = None):
        return None

    def get_embedding_model(self):
        return None


async def _bootstrapper_with_db(tmp_path: Path) -> tuple[Bootstrapper, Database]:
    bt = make_bootstrapper(make_settings(tmp_path))
    db = Database(bt.settings.db_path)
    await db.open()
    await apply_migrations(db)
    bt.container.register_instance(Database, db)
    return bt, db


async def test_factory_registered_and_resolves_sqlite_index(tmp_path: Path) -> None:
    bt, db = await _bootstrapper_with_db(tmp_path)
    try:
        assert bt.container.has(VectorIndex)
        idx: VectorIndex = bt.container.resolve(VectorIndex)
        assert isinstance(idx, SqliteVectorIndex)
        # Lazy factory is a cached singleton.
        assert bt.container.resolve(VectorIndex) is idx
    finally:
        await db.close()


async def test_container_attaches_embedding_from_router(tmp_path: Path) -> None:
    bt, db = await _bootstrapper_with_db(tmp_path)
    bt.container.register_instance(ModelRouter, _RouterWithEmbedding(HashingEmbeddingModel(dim=128)))
    try:
        idx = bt.container.resolve(VectorIndex)
        assert idx.tag != "unattached"
        assert idx.tag.startswith("hashing:")
    finally:
        await db.close()


async def test_container_degrades_gracefully_without_embedding(tmp_path: Path) -> None:
    bt, db = await _bootstrapper_with_db(tmp_path)
    bt.container.register_instance(ModelRouter, _RouterWithoutEmbedding())
    try:
        idx = bt.container.resolve(VectorIndex)
        assert idx.tag == "unattached"  # no crash; MemoryInterface degrades like this too
    finally:
        await db.close()


async def test_memory_interface_built_from_container_index(tmp_path: Path) -> None:
    bt, db = await _bootstrapper_with_db(tmp_path)
    bt.container.register_instance(ModelRouter, _RouterWithEmbedding(HashingEmbeddingModel(dim=128)))
    index = bt.container.resolve(VectorIndex)
    await index.ensure_table()
    cognitive = CognitiveMemorySupport(db)
    await cognitive.ensure_content_hash_column()
    system = SQLiteMemorySystem(
        MemoryStore(db), cognitive, InMemoryEventBus(), bt.settings, index=index
    )
    # Built from the container-resolved index (the DI path the task asks for).
    iface = MemoryInterface(system, index)
    try:
        assert await iface.lookup("unrelated nonsense query x yz") is None
        await iface.write(QUESTION, ANSWER)
        hit = await iface.lookup(QUESTION)
        assert hit is not None
        assert hit.value == ANSWER
    finally:
        await db.close()

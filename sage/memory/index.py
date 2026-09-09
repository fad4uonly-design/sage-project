"""Vector index for cognitive memory — the TurboVec concept made SAGE-owned.

A minimal, tag-aware vector index persisted alongside memories in SQLite.
Vectors are L2-normalized float32 rows; search is exact cosine via numpy,
which is appropriate at personal scale (thousands of memories, not millions).

The index is keyed by the embedding model that produced it (`tag`); when the
embedding source changes, the index rebuilds for the new tag instead of
silently mixing incompatible vector spaces. The index itself is replaceable:
any implementation satisfying :class:`VectorIndex` can be swapped in without
touching the memory system.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

import numpy as np

from sage.db.connection import Database
from sage.logging import get_logger
from sage.models.interfaces import EmbeddingModel
from sage.utils.time import utcnow_iso

log = get_logger(__name__)


@runtime_checkable
class VectorIndex(Protocol):
    """Replaceable vector index contract (the TurboVec slot)."""

    tag: str

    def attach(self, embedding: EmbeddingModel) -> None: ...

    async def ensure_table(self) -> None: ...

    async def upsert(self, memory_id: str, content: str) -> None: ...

    async def remove(self, memory_id: str) -> None: ...

    async def search(self, query: str, *, limit: int = 10) -> list[tuple[str, float]]: ...

    async def rebuild(self, items: Sequence[tuple[str, str]]) -> int: ...

    async def count(self) -> int: ...


class SqliteVectorIndex:
    """SQLite-backed brute-force cosine index (exact search, personal scale)."""

    _BATCH = 32
    _MIN_SCORE = 0.05

    def __init__(self, db: Database) -> None:
        self.db = db
        self.tag: str = "unattached"
        self._embedding: EmbeddingModel | None = None
        self._matrix: np.ndarray | None = None
        self._ids: list[str] = []

    # -- attachment -----------------------------------------------------

    def attach(self, embedding: EmbeddingModel) -> None:
        new_tag = f"{embedding.provider}:{embedding.model_name}"
        if self._embedding is embedding and self.tag == new_tag:
            return
        self._embedding = embedding
        self.tag = new_tag
        self._invalidate()
        log.debug("memory.index_attached", tag=self.tag)

    def _require_embedding(self) -> EmbeddingModel:
        if self._embedding is None:
            raise RuntimeError("VectorIndex has no embedding model attached.")
        return self._embedding

    def _invalidate(self) -> None:
        self._matrix = None
        self._ids = []

    # -- lifecycle ------------------------------------------------------

    async def ensure_table(self) -> None:
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_vectors (
                memory_id TEXT PRIMARY KEY,
                model_tag TEXT NOT NULL,
                dim INTEGER NOT NULL,
                vector BLOB NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_vectors_tag ON memory_vectors(model_tag)"
        )

    async def count(self) -> int:
        val = await self.db.scalar(
            "SELECT COUNT(*) FROM memory_vectors WHERE model_tag = ?", (self.tag,)
        )
        return int(val or 0)

    # -- writes ---------------------------------------------------------

    async def upsert(self, memory_id: str, content: str) -> None:
        embedding = self._require_embedding()
        vectors = await embedding.embed([content])
        if not vectors:
            return
        vec = self._normalized(np.asarray(vectors[0], dtype=np.float32))
        await self._write(
            [(memory_id, self.tag, int(vec.size), vec.tobytes(), utcnow_iso())]
        )
        self._invalidate()

    async def remove(self, memory_id: str) -> None:
        await self.db.execute(
            "DELETE FROM memory_vectors WHERE memory_id = ?", (memory_id,)
        )
        self._invalidate()

    async def rebuild(self, items: Sequence[tuple[str, str]]) -> int:
        """Replace all vectors for the active tag from (id, content) pairs."""
        embedding = self._require_embedding()
        await self.db.execute(
            "DELETE FROM memory_vectors WHERE model_tag = ?", (self.tag,)
        )
        self._invalidate()

        written = 0
        for start in range(0, len(items), self._BATCH):
            batch = items[start : start + self._BATCH]
            texts = [content for _, content in batch]
            vectors = await embedding.embed(texts)
            rows: list[tuple[str, str, int, bytes, str]] = []
            for (memory_id, _), vec in zip(batch, vectors, strict=False):
                arr = self._normalized(np.asarray(vec, dtype=np.float32))
                rows.append(
                    (memory_id, self.tag, int(arr.size), arr.tobytes(), utcnow_iso())
                )
            if rows:
                await self._write(rows)
            written += len(rows)

        log.info("memory.index_rebuilt", tag=self.tag, vectors=written)
        return written

    async def _write(self, rows: list[tuple[str, str, int, bytes, str]]) -> None:
        await self.db.executemany(
            """
            INSERT INTO memory_vectors (memory_id, model_tag, dim, vector, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(memory_id) DO UPDATE SET
                model_tag = excluded.model_tag,
                dim = excluded.dim,
                vector = excluded.vector,
                updated_at = excluded.updated_at
            """,
            rows,
        )

    # -- search ---------------------------------------------------------

    async def search(
        self, query: str, *, limit: int = 10
    ) -> list[tuple[str, float]]:
        if limit <= 0 or not query.strip():
            return []
        embedding = self._require_embedding()

        matrix, ids = await self._load_matrix()
        if matrix is None or not ids:
            return []

        query_vectors = await embedding.embed([query])
        if not query_vectors:
            return []
        query_vec = self._normalized(np.asarray(query_vectors[0], dtype=np.float32))
        if query_vec.size != matrix.shape[1]:
            log.warning(
                "memory.index_dim_mismatch",
                query_dim=int(query_vec.size),
                index_dim=int(matrix.shape[1]),
            )
            return []

        scores = matrix @ query_vec
        order = np.argsort(-scores)[:limit]
        return [
            (ids[i], float(scores[i]))
            for i in order
            if float(scores[i]) > self._MIN_SCORE
        ]

    async def _load_matrix(self) -> tuple[np.ndarray | None, list[str]]:
        if self._matrix is not None:
            return self._matrix, self._ids

        rows = await self.db.fetchall(
            "SELECT memory_id, dim, vector FROM memory_vectors WHERE model_tag = ?",
            (self.tag,),
        )
        if not rows:
            return None, []

        dim_counts = Counter(int(row["dim"]) for row in rows)
        dim, _ = dim_counts.most_common(1)[0]
        if len(dim_counts) > 1:
            log.warning("memory.index_mixed_dims", dims=dict(dim_counts), using=dim)

        ids: list[str] = []
        vectors: list[np.ndarray] = []
        for row in rows:
            if int(row["dim"]) != dim:
                continue
            ids.append(row["memory_id"])
            vectors.append(np.frombuffer(row["vector"], dtype=np.float32))
        if not vectors:
            return None, []

        matrix = np.vstack(vectors)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        self._matrix = matrix / norms
        self._ids = ids
        return self._matrix, self._ids

    @staticmethod
    def _normalized(vec: np.ndarray) -> np.ndarray:
        norm = float(np.linalg.norm(vec))
        return vec / norm if norm > 0.0 else vec

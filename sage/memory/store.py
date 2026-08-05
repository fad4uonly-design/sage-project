"""SQLite persistence for memories."""

from __future__ import annotations

from typing import Any

from sage.db.connection import Database
from sage.db.repository import BaseRepository
from sage.memory.models import MemoryItem, MemoryType
from sage.utils.time import utcnow_iso


class MemoryStore(BaseRepository):
    def __init__(self, db: Database) -> None:
        super().__init__(db)
        self._has_hash: bool | None = None
        self._has_version: bool | None = None

    async def _column_flags(self) -> tuple[bool, bool]:
        if self._has_hash is None or self._has_version is None:
            cols = await self.db.fetchall("PRAGMA table_info(memories)")
            names = {r["name"] for r in cols}
            self._has_hash = "content_hash" in names
            self._has_version = "version" in names
        return bool(self._has_hash), bool(self._has_version)

    def _row_to_item(self, row: Any) -> MemoryItem:
        keys = set(row.keys()) if hasattr(row, "keys") else set()
        return MemoryItem(
            id=row["id"],
            type=MemoryType(row["type"]),
            content=row["content"],
            summary=row["summary"],
            importance=row["importance"],
            confidence=row["confidence"],
            source=row["source"],
            source_ref=row["source_ref"],
            tags=self.loads(row["tags"], []),
            metadata=self.loads(row["metadata"], {}),
            embedding_id=row["embedding_id"],
            content_hash=row["content_hash"] if "content_hash" in keys else None,
            version=int(row["version"]) if "version" in keys else 1,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_accessed_at=row["last_accessed_at"],
            access_count=row["access_count"],
            expires_at=row["expires_at"],
            deleted_at=row["deleted_at"],
        )

    async def insert(self, item: MemoryItem) -> None:
        has_hash, has_version = await self._column_flags()
        if has_hash and has_version:
            await self.db.execute(
                """
                INSERT INTO memories (
                    id, type, content, summary, importance, confidence,
                    source, source_ref, tags, metadata, embedding_id,
                    content_hash, version,
                    created_at, updated_at, last_accessed_at, access_count,
                    expires_at, deleted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.type.value,
                    item.content,
                    item.summary,
                    item.importance,
                    item.confidence,
                    item.source,
                    item.source_ref,
                    self.dumps(item.tags),
                    self.dumps(item.metadata),
                    item.embedding_id,
                    item.content_hash,
                    item.version,
                    item.created_at,
                    item.updated_at,
                    item.last_accessed_at,
                    item.access_count,
                    item.expires_at,
                    item.deleted_at,
                ),
            )
        else:
            await self.db.execute(
                """
                INSERT INTO memories (
                    id, type, content, summary, importance, confidence,
                    source, source_ref, tags, metadata, embedding_id,
                    created_at, updated_at, last_accessed_at, access_count,
                    expires_at, deleted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.type.value,
                    item.content,
                    item.summary,
                    item.importance,
                    item.confidence,
                    item.source,
                    item.source_ref,
                    self.dumps(item.tags),
                    self.dumps(item.metadata),
                    item.embedding_id,
                    item.created_at,
                    item.updated_at,
                    item.last_accessed_at,
                    item.access_count,
                    item.expires_at,
                    item.deleted_at,
                ),
            )

    async def get(self, memory_id: str) -> MemoryItem | None:
        row = await self.db.fetchone(
            "SELECT * FROM memories WHERE id = ? AND deleted_at IS NULL",
            (memory_id,),
        )
        return self._row_to_item(row) if row else None

    async def update_fields(self, memory_id: str, fields: dict[str, Any]) -> MemoryItem | None:
        if not fields:
            return await self.get(memory_id)

        allowed = {
            "type",
            "content",
            "summary",
            "importance",
            "confidence",
            "source",
            "source_ref",
            "tags",
            "metadata",
            "embedding_id",
            "content_hash",
            "version",
            "last_accessed_at",
            "access_count",
            "expires_at",
            "deleted_at",
        }
        sets: list[str] = []
        values: list[Any] = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key == "type" and isinstance(value, MemoryType):
                value = value.value
            if key in ("tags", "metadata"):
                value = self.dumps(value)
            sets.append(f"{key} = ?")
            values.append(value)

        sets.append("updated_at = ?")
        values.append(utcnow_iso())
        values.append(memory_id)

        await self.db.execute(
            f"UPDATE memories SET {', '.join(sets)} WHERE id = ?",
            tuple(values),
        )
        return await self.get(memory_id)

    async def soft_delete(self, memory_id: str) -> bool:
        item = await self.get(memory_id)
        if item is None:
            return False
        await self.db.execute(
            "UPDATE memories SET deleted_at = ?, updated_at = ? WHERE id = ?",
            (utcnow_iso(), utcnow_iso(), memory_id),
        )
        return True

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        types: list[str] | None = None,
    ) -> list[MemoryItem]:
        """
        Simple ranked keyword search.

        Matches if ANY significant token appears in content/summary/tags.
        Ranking: importance, access_count, recency.
        """
        raw = query.strip()
        tokens = [t for t in raw.split() if len(t) > 1] or ([raw] if raw else [])
        if not tokens:
            return await self.list_recent(limit=limit)

        token_clauses: list[str] = []
        params: list[Any] = []
        for tok in tokens[:8]:
            like = f"%{tok}%"
            token_clauses.append(
                "(content LIKE ? OR IFNULL(summary, '') LIKE ? OR tags LIKE ?)"
            )
            params.extend([like, like, like])

        type_clause = ""
        if types:
            placeholders = ",".join("?" for _ in types)
            type_clause = f" AND type IN ({placeholders})"
            params.extend(types)

        params.append(limit)
        sql = f"""
            SELECT * FROM memories
            WHERE deleted_at IS NULL
              AND (expires_at IS NULL OR expires_at > datetime('now'))
              AND ({' OR '.join(token_clauses)})
              {type_clause}
            ORDER BY importance DESC, access_count DESC, created_at DESC
            LIMIT ?
        """
        rows = await self.db.fetchall(sql, tuple(params))
        return [self._row_to_item(r) for r in rows]

    async def list_recent(self, *, limit: int = 10) -> list[MemoryItem]:
        rows = await self.db.fetchall(
            """
            SELECT * FROM memories
            WHERE deleted_at IS NULL
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [self._row_to_item(r) for r in rows]

    async def count(self, *, include_deleted: bool = False) -> int:
        if include_deleted:
            val = await self.db.scalar("SELECT COUNT(*) FROM memories")
        else:
            val = await self.db.scalar("SELECT COUNT(*) FROM memories WHERE deleted_at IS NULL")
        return int(val or 0)

    async def expire_due(self) -> int:
        cur = await self.db.execute(
            """
            UPDATE memories
            SET deleted_at = ?, updated_at = ?
            WHERE deleted_at IS NULL
              AND expires_at IS NOT NULL
              AND expires_at <= ?
            """,
            (utcnow_iso(), utcnow_iso(), utcnow_iso()),
        )
        return cur.rowcount or 0

    async def find_similar_content(self, content: str, *, limit: int = 5) -> list[MemoryItem]:
        snippet = content.strip()[:200]
        if not snippet:
            return []
        rows = await self.db.fetchall(
            """
            SELECT * FROM memories
            WHERE deleted_at IS NULL
              AND content LIKE ?
            ORDER BY importance DESC
            LIMIT ?
            """,
            (f"%{snippet}%", limit),
        )
        return [self._row_to_item(r) for r in rows]

    async def list_all_active(self, *, limit: int = 500) -> list[MemoryItem]:
        rows = await self.db.fetchall(
            """
            SELECT * FROM memories
            WHERE deleted_at IS NULL
            ORDER BY importance DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [self._row_to_item(r) for r in rows]

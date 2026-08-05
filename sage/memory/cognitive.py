"""
Cognitive memory pipeline helpers.

Store → fingerprint → duplicate detection → importance scoring →
relationship detection → version history → consolidation
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any

from sage.db.connection import Database
from sage.db.repository import BaseRepository
from sage.logging import get_logger
from sage.memory.models import MemoryItem
from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso

log = get_logger(__name__)

_STOP = frozenset(
    """
    a an the and or but if in on at to for of is are was were be been being
    this that these those it its i me my we our you your they them their
    with from as by about into over after before between
    """.split()
)


def content_fingerprint(content: str) -> str:
    normalized = " ".join(content.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def extract_terms(content: str, *, limit: int = 12) -> list[str]:
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_\-]{2,}", content.lower())
    filtered = [t for t in tokens if t not in _STOP]
    counts = Counter(filtered)
    return [t for t, _ in counts.most_common(limit)]


def score_importance(item: MemoryItem) -> float:
    """Heuristic importance from type, length, source, and explicit value."""
    base = item.importance
    type_boost = {
        "preference": 0.15,
        "relationship": 0.1,
        "fact": 0.05,
        "long_term": 0.08,
        "episodic": 0.0,
        "short_term": -0.1,
        "project": 0.05,
        "technical": 0.05,
        "semantic": 0.05,
    }.get(item.type.value, 0.0)
    source_boost = 0.1 if item.source == "user" else 0.0
    length_factor = min(0.1, len(item.content) / 2000.0)
    # Signal words
    lower = item.content.lower()
    signal = 0.0
    for word, w in (
        ("always", 0.08),
        ("never", 0.08),
        ("important", 0.1),
        ("critical", 0.12),
        ("prefer", 0.1),
        ("my name", 0.15),
        ("birthday", 0.12),
        ("password", -0.2),  # discourage storing secrets as memory
    ):
        if word in lower:
            signal += w
    score = base + type_boost + source_boost + length_factor + signal
    return float(max(0.0, min(1.0, score)))


class CognitiveMemorySupport(BaseRepository):
    """Persistence helpers for relations, versions, fingerprints."""

    def __init__(self, db: Database) -> None:
        super().__init__(db)

    async def ensure_content_hash_column(self) -> None:
        cols = await self.db.fetchall("PRAGMA table_info(memories)")
        names = {r["name"] for r in cols}
        if "content_hash" not in names:
            await self.db.execute("ALTER TABLE memories ADD COLUMN content_hash TEXT")
            await self.db.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_content_hash ON memories(content_hash)"
            )
        if "version" not in names:
            await self.db.execute(
                "ALTER TABLE memories ADD COLUMN version INTEGER NOT NULL DEFAULT 1"
            )

    async def find_by_hash(self, content_hash: str) -> str | None:
        row = await self.db.fetchone(
            "SELECT id FROM memories WHERE content_hash = ? AND deleted_at IS NULL LIMIT 1",
            (content_hash,),
        )
        return row["id"] if row else None

    async def set_hash_and_version(
        self, memory_id: str, content_hash: str, version: int = 1
    ) -> None:
        await self.db.execute(
            "UPDATE memories SET content_hash = ?, version = ? WHERE id = ?",
            (content_hash, version, memory_id),
        )

    async def add_version(
        self,
        memory_id: str,
        version: int,
        content: str,
        *,
        summary: str | None,
        importance: float,
        confidence: float,
        metadata: dict[str, Any],
        reason: str = "",
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO memory_versions
                (id, memory_id, version, content, summary, importance, confidence, metadata, changed_at, change_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("mver"),
                memory_id,
                version,
                content,
                summary,
                importance,
                confidence,
                self.dumps(metadata),
                utcnow_iso(),
                reason,
            ),
        )

    async def link(
        self,
        source_id: str,
        target_id: str,
        relation: str,
        *,
        weight: float = 1.0,
        confidence: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        rid = new_id("mrel")
        await self.db.execute(
            """
            INSERT INTO memory_relations
                (id, source_id, target_id, relation, weight, confidence, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rid,
                source_id,
                target_id,
                relation,
                weight,
                confidence,
                self.dumps(metadata or {}),
                utcnow_iso(),
            ),
        )
        return rid

    async def find_related_by_terms(
        self, terms: list[str], *, exclude_id: str, limit: int = 5
    ) -> list[tuple[str, float]]:
        if not terms:
            return []
        scored: dict[str, float] = {}
        for term in terms[:8]:
            rows = await self.db.fetchall(
                """
                SELECT id, importance FROM memories
                WHERE deleted_at IS NULL
                  AND id != ?
                  AND (content LIKE ? OR tags LIKE ?)
                LIMIT 20
                """,
                (exclude_id, f"%{term}%", f"%{term}%"),
            )
            for r in rows:
                scored[r["id"]] = scored.get(r["id"], 0.0) + 0.15 + float(r["importance"]) * 0.1
        ranked = sorted(scored.items(), key=lambda x: x[1], reverse=True)
        return ranked[:limit]

    async def list_relations(self, memory_id: str) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            """
            SELECT * FROM memory_relations
            WHERE source_id = ? OR target_id = ?
            ORDER BY created_at DESC
            """,
            (memory_id, memory_id),
        )
        return [
            {
                "id": r["id"],
                "source_id": r["source_id"],
                "target_id": r["target_id"],
                "relation": r["relation"],
                "weight": r["weight"],
                "confidence": r["confidence"],
            }
            for r in rows
        ]

    async def merge_duplicate(self, keep_id: str, drop_id: str) -> None:
        """Soft-delete drop_id and bump keep importance slightly."""
        await self.db.execute(
            "UPDATE memories SET deleted_at = ?, updated_at = ? WHERE id = ?",
            (utcnow_iso(), utcnow_iso(), drop_id),
        )
        await self.db.execute(
            """
            UPDATE memories
            SET importance = MIN(1.0, importance + 0.05),
                access_count = access_count + 1,
                updated_at = ?
            WHERE id = ?
            """,
            (utcnow_iso(), keep_id),
        )
        await self.link(keep_id, drop_id, "duplicate_of", weight=1.0, confidence=0.95)

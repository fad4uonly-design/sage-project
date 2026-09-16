"""Memory system service and module — cognitive pipeline."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Any

from sage.config.settings import Settings
from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.core.scheduler import Scheduler
from sage.db.connection import Database
from sage.events.bus import EventBus
from sage.events.events import Event, MemoryEvents
from sage.logging import get_logger
from sage.memory.cognitive import (
    CognitiveMemorySupport,
    content_fingerprint,
    extract_terms,
    score_importance,
)
from sage.memory.index import SqliteVectorIndex, VectorIndex
from sage.memory.interfaces import MemorySystem
from sage.memory.models import ConsolidationReport, MemoryItem, MemoryType
from sage.memory.store import MemoryStore
from sage.models.interfaces import EmbeddingModel, ModelRouter
from sage.utils.time import utcnow, utcnow_iso

log = get_logger(__name__)


class SQLiteMemorySystem:
    """
    Cognitive memory backed by SQLite.

    Pipeline on store:
      fingerprint → duplicate detect → importance score →
      tags/terms → persist → version snapshot → relationship links
    """

    def __init__(
        self,
        store: MemoryStore,
        cognitive: CognitiveMemorySupport,
        events: EventBus,
        settings: Settings,
        *,
        index: VectorIndex | None = None,
        router_resolver: Callable[[], ModelRouter | None] | None = None,
    ) -> None:
        self._store = store
        self._cog = cognitive
        self._events = events
        self._settings = settings
        self._index = index
        self._router_resolver = router_resolver
        self._embedding: EmbeddingModel | None = None
        self._backfill_done = False

    async def store(self, item: MemoryItem) -> str:
        return await self.store_cognitive(item)

    async def store_cognitive(self, item: MemoryItem) -> str:
        if item.type == MemoryType.SHORT_TERM and item.expires_at is None:
            ttl = timedelta(minutes=self._settings.memory.short_term_ttl_minutes)
            item.expires_at = (utcnow() + ttl).isoformat().replace("+00:00", "Z")

        # Fingerprint + duplicate detection
        fp = content_fingerprint(item.content)
        item.content_hash = fp
        existing_id = await self._cog.find_by_hash(fp)
        if existing_id:
            existing = await self._store.get(existing_id)
            if existing:
                # Reinforce existing memory instead of duplicating
                new_imp = min(1.0, max(existing.importance, item.importance) + 0.05)
                new_conf = min(1.0, max(existing.confidence, item.confidence) + 0.02)
                await self._store.update_fields(
                    existing_id,
                    {
                        "importance": new_imp,
                        "confidence": new_conf,
                        "access_count": existing.access_count + 1,
                        "last_accessed_at": utcnow_iso(),
                    },
                )
                log.info("memory.duplicate_reinforced", id=existing_id, hash=fp[:12])
                await self._events.publish(
                    Event(
                        type=MemoryEvents.UPDATED,
                        payload={"id": existing_id, "reason": "duplicate_reinforce"},
                        source="memory",
                    )
                )
                return existing_id

        # Importance scoring
        item.importance = score_importance(item)

        # Auto-tags from terms
        terms = extract_terms(item.content)
        for t in terms[:5]:
            if t not in item.tags:
                item.tags.append(t)
        item.metadata = {
            **item.metadata,
            "terms": terms,
            "pipeline": "cognitive_v1",
        }
        if not item.summary:
            item.summary = item.content[:200] + ("..." if len(item.content) > 200 else "")

        item.version = 1
        await self._store.insert(item)
        await self._cog.set_hash_and_version(item.id, fp, version=1)
        await self._cog.add_version(
            item.id,
            1,
            item.content,
            summary=item.summary,
            importance=item.importance,
            confidence=item.confidence,
            metadata=item.metadata,
            reason="create",
        )
        await self._index_upsert(item.id, item.content)

        # Relationship detection
        related = await self._cog.find_related_by_terms(terms, exclude_id=item.id, limit=5)
        for rel_id, weight in related:
            await self._cog.link(
                item.id,
                rel_id,
                "related_to",
                weight=min(1.0, weight),
                confidence=min(0.9, weight),
                metadata={"via": "term_overlap"},
            )

        await self._events.publish(
            Event(
                type=MemoryEvents.CREATED,
                payload={
                    "id": item.id,
                    "type": item.type.value,
                    "importance": item.importance,
                    "relations": len(related),
                },
                source="memory",
            )
        )
        log.debug(
            "memory.stored_cognitive",
            id=item.id,
            type=item.type.value,
            importance=item.importance,
            relations=len(related),
        )
        return item.id

    async def recall(
        self,
        query: str,
        *,
        limit: int | None = None,
        types: Sequence[MemoryType] | None = None,
    ) -> list[MemoryItem]:
        lim = limit if limit is not None else self._settings.memory.default_recall_limit
        type_vals = [t.value for t in types] if types else None

        if query.strip():
            items = await self._blended_recall(query, lim, type_vals)
        else:
            items = await self._store.list_recent(limit=lim)

        await self._touch(items)
        return items

    async def recall_scored(
        self,
        query: str,
        *,
        limit: int | None = None,
        types: Sequence[MemoryType] | None = None,
    ) -> list[tuple[MemoryItem, float]]:
        """Blended recall that KEEPS the per-item relevance score.

        Returns ``(item, relevance)`` pairs. ``relevance`` is the semantic /
        lexical similarity of the hit (max of token overlap and vector cosine —
        the primary ranking signal), so downstream layers can rank by relevance
        instead of re-deriving importance-based scores. Ordering follows the
        same blended rank as :meth:`recall`; importance and recency remain
        secondary signals inside that ordering only.
        """
        lim = limit if limit is not None else self._settings.memory.default_recall_limit
        type_vals = [t.value for t in types] if types else None

        if query.strip():
            ranked = await self._blended_recall_scored(query, lim, type_vals)
            items = [item for item, _ in ranked]
        else:
            ranked = []
            items = await self._store.list_recent(limit=lim)

        await self._touch(items)
        relevance = {item.id: rel for item, rel in ranked}
        return [(item, relevance.get(item.id, 0.0)) for item in items]

    async def _touch(self, items: list[MemoryItem]) -> None:
        now = utcnow_iso()
        for item in items:
            await self._store.update_fields(
                item.id,
                {"last_accessed_at": now, "access_count": item.access_count + 1},
            )

    # -- vector index plumbing (TurboVec slot) ---------------------------

    def _resolve_index(self) -> VectorIndex | None:
        """Return the index with an embedding attached, if one is available."""
        if self._index is None:
            return None
        if self._embedding is None and self._router_resolver is not None:
            router = self._router_resolver()
            if router is None:
                return None
            self._embedding = router.get_embedding_model()
            self._index.attach(self._embedding)
            log.info("memory.index_attached", tag=self._index.tag)
        if self._embedding is None:
            return None
        return self._index

    async def _index_upsert(self, memory_id: str, content: str) -> None:
        index = self._resolve_index()
        if index is None:
            return
        try:
            await index.upsert(memory_id, content)
        except Exception:
            log.exception("memory.index_upsert_failed")

    async def _index_remove(self, memory_id: str) -> None:
        index = self._resolve_index()
        if index is None:
            return
        try:
            await index.remove(memory_id)
        except Exception:
            log.exception("memory.index_remove_failed")

    async def sync_index(self, *, force: bool = False) -> int:
        """Best-effort backfill/rebuild of the vector index from active memories."""
        index = self._resolve_index()
        if index is None:
            return 0
        if self._backfill_done and not force:
            return 0
        self._backfill_done = True
        try:
            active = await self._store.list_all_active(limit=1000)
            if not active:
                return 0
            if not force and await index.count() >= len(active):
                return 0
            return await index.rebuild([(item.id, item.content) for item in active])
        except Exception:
            log.exception("memory.index_sync_failed")
            return 0

    async def _blended_recall(
        self,
        query: str,
        limit: int,
        type_vals: list[str] | None,
    ) -> list[MemoryItem]:
        """Keyword recall union vector recall, scored sim/importance/recency."""
        ranked = await self._blended_recall_scored(query, limit, type_vals)
        return [item for item, _ in ranked]

    async def _blended_recall_scored(
        self,
        query: str,
        limit: int,
        type_vals: list[str] | None,
    ) -> list[tuple[MemoryItem, float]]:
        """Blended recall keeping each item's relevance score.

        The carried score is the semantic/lexical relevance (max of token
        overlap and vector cosine) — NOT the blended rank, so importance and
        recency stay secondary ordering signals and never masquerade as
        relevance downstream.
        """
        await self.sync_index()

        tokens = {t.lower() for t in query.split() if len(t) > 2}

        def lexical_overlap(item: MemoryItem) -> float:
            if not tokens:
                return 0.0
            hay = set(item.content.lower().split())
            hay.update((item.summary or "").lower().split())
            hay.update(t.lower() for t in item.tags)
            return len(tokens & hay) / len(tokens)

        candidates: dict[str, tuple[float, MemoryItem]] = {}
        for item in await self._store.search(query, limit=limit * 2, types=type_vals):
            candidates[item.id] = (lexical_overlap(item), item)

        index = self._resolve_index()
        if index is not None:
            try:
                hits = await index.search(query, limit=limit * 2)
            except Exception:
                log.exception("memory.index_search_failed")
                hits = []
            for memory_id, sim in hits:
                existing = candidates.get(memory_id)
                if existing is not None:
                    score, item = existing
                    candidates[memory_id] = (max(score, sim), item)
                    continue
                fetched = await self._store.get(memory_id)
                if fetched is None or (type_vals and fetched.type.value not in type_vals):
                    continue
                candidates[memory_id] = (sim, fetched)

        if not candidates:
            return []

        def recency(item: MemoryItem) -> float:
            try:
                stamp = (item.updated_at or item.created_at).replace("Z", "+00:00")
                age_days = max(
                    0.0,
                    (utcnow() - datetime.fromisoformat(stamp)).total_seconds() / 86400.0,
                )
            except (ValueError, TypeError):
                return 0.5
            return float(0.5 ** (age_days / 30.0))

        def final_score(entry: tuple[float, MemoryItem]) -> float:
            sim, item = entry
            return 0.45 * sim + 0.35 * item.importance + 0.20 * recency(item)

        ranked = sorted(candidates.values(), key=final_score, reverse=True)
        return [(item, sim) for sim, item in ranked[:limit]]

    async def get(self, memory_id: str) -> MemoryItem | None:
        return await self._store.get(memory_id)

    async def update(self, memory_id: str, **fields: Any) -> MemoryItem:
        current = await self._store.get(memory_id)
        if current is None:
            raise KeyError(f"Memory not found: {memory_id}")

        # Version history when content changes
        if "content" in fields and fields["content"] != current.content:
            new_version = current.version + 1
            fields["version"] = new_version
            fields["content_hash"] = content_fingerprint(str(fields["content"]))
            if "importance" not in fields:
                probe = current.model_copy(update={"content": str(fields["content"])})
                fields["importance"] = score_importance(probe)

        item = await self._store.update_fields(memory_id, fields)
        if item is None:
            raise KeyError(f"Memory not found: {memory_id}")

        if "content" in fields:
            await self._cog.add_version(
                memory_id,
                item.version,
                item.content,
                summary=item.summary,
                importance=item.importance,
                confidence=item.confidence,
                metadata=item.metadata,
                reason="update",
            )
            await self._index_upsert(memory_id, item.content)

        await self._events.publish(
            Event(
                type=MemoryEvents.UPDATED,
                payload={"id": memory_id, "fields": list(fields.keys())},
                source="memory",
            )
        )
        return item

    async def forget(self, memory_id: str, *, reason: str = "") -> bool:
        ok = await self._store.soft_delete(memory_id)
        if ok:
            await self._events.publish(
                Event(
                    type=MemoryEvents.FORGOTTEN,
                    payload={"id": memory_id, "reason": reason},
                    source="memory",
                )
            )
            await self._index_remove(memory_id)
        return ok

    async def consolidate(self) -> ConsolidationReport:
        expired = await self._store.expire_due()
        promoted = 0
        merged = 0
        related = 0
        rescored = 0

        # Promote high-importance short_term → long_term
        rows = await self._store.db.fetchall(
            "SELECT id, importance FROM memories WHERE type = ? AND deleted_at IS NULL AND importance >= 0.7",
            (MemoryType.SHORT_TERM.value,),
        )
        for row in rows:
            await self._store.update_fields(
                row["id"],
                {"type": MemoryType.LONG_TERM, "expires_at": None},
            )
            promoted += 1

        # Rescore + relate batch
        active = await self._store.list_all_active(limit=200)
        seen_hashes: dict[str, str] = {}
        for item in active:
            # Rescore drift
            new_score = score_importance(item)
            if abs(new_score - item.importance) >= 0.05:
                await self._store.update_fields(item.id, {"importance": new_score})
                rescored += 1

            fp = item.content_hash or content_fingerprint(item.content)
            if fp in seen_hashes and seen_hashes[fp] != item.id:
                await self._cog.merge_duplicate(seen_hashes[fp], item.id)
                await self._index_remove(item.id)
                merged += 1
            else:
                seen_hashes[fp] = item.id
                if not item.content_hash:
                    await self._cog.set_hash_and_version(item.id, fp, version=item.version)

            # Sparse relationship fill
            terms = extract_terms(item.content)
            links = await self._cog.find_related_by_terms(terms, exclude_id=item.id, limit=2)
            existing = await self._cog.list_relations(item.id)
            existing_pairs = {(r["source_id"], r["target_id"], r["relation"]) for r in existing}
            for rel_id, weight in links:
                key = (item.id, rel_id, "related_to")
                if key not in existing_pairs:
                    await self._cog.link(
                        item.id, rel_id, "related_to", weight=min(1.0, weight), confidence=0.5
                    )
                    related += 1

        report = ConsolidationReport(
            expired=expired,
            promoted=promoted,
            merged=merged,
            related=related,
            rescored=rescored,
            message=(
                f"expired={expired} promoted={promoted} merged={merged} "
                f"related={related} rescored={rescored}"
            ),
        )
        await self._events.publish(
            Event(
                type=MemoryEvents.CONSOLIDATED,
                payload=report.model_dump(),
                source="memory",
            )
        )
        log.info("memory.consolidated", **report.model_dump())
        return report

    async def count(self, *, include_deleted: bool = False) -> int:
        return await self._store.count(include_deleted=include_deleted)

    async def relations(self, memory_id: str) -> list[dict[str, Any]]:
        return await self._cog.list_relations(memory_id)


class MemoryModule(BaseModule):
    name = "memory"
    version = "0.1.1"
    is_critical = True

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._system: SQLiteMemorySystem | None = None

    async def _on_initialize(self) -> None:
        db = self.container.resolve(Database)
        events = self.container.resolve(EventBus)
        settings = self.container.resolve(Settings)
        store = MemoryStore(db)
        cognitive = CognitiveMemorySupport(db)
        await cognitive.ensure_content_hash_column()
        index = SqliteVectorIndex(db)
        await index.ensure_table()
        self._system = SQLiteMemorySystem(
            store,
            cognitive,
            events,
            settings,
            index=index,
            router_resolver=lambda: self.container.try_resolve(ModelRouter),
        )
        self.container.register_instance(MemorySystem, self._system)
        self.container.register_instance(SQLiteMemorySystem, self._system)

    async def _on_start(self) -> None:
        settings = self.container.resolve(Settings)
        scheduler = self.container.try_resolve(Scheduler)
        if self._system is not None:
            await self._system.sync_index()
        if scheduler and self._system:
            interval = settings.memory.consolidation_interval_minutes * 60
            system = self._system

            async def _job() -> None:
                await system.consolidate()

            scheduler.register("memory.consolidate", _job, interval_seconds=float(interval))

    async def _on_health(self) -> HealthStatus | None:
        if self._system is None:
            return HealthStatus.unhealthy(self.name, "not initialized", critical=True)
        count = await self._system.count()
        return HealthStatus.healthy(self.name, "ok", memory_count=count)

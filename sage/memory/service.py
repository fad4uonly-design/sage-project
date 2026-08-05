"""Memory system service and module."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
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
from sage.memory.interfaces import MemorySystem
from sage.memory.models import ConsolidationReport, MemoryItem, MemoryType
from sage.memory.store import MemoryStore
from sage.utils.time import utcnow, utcnow_iso

log = get_logger(__name__)


class SQLiteMemorySystem:
    """Production memory implementation backed by SQLite."""

    def __init__(self, store: MemoryStore, events: EventBus, settings: Settings) -> None:
        self._store = store
        self._events = events
        self._settings = settings

    async def store(self, item: MemoryItem) -> str:
        if item.type == MemoryType.SHORT_TERM and item.expires_at is None:
            ttl = timedelta(minutes=self._settings.memory.short_term_ttl_minutes)
            item.expires_at = (utcnow() + ttl).isoformat().replace("+00:00", "Z")

        await self._store.insert(item)
        await self._events.publish(
            Event(
                type=MemoryEvents.CREATED,
                payload={"id": item.id, "type": item.type.value},
                source="memory",
            )
        )
        log.debug("memory.stored", id=item.id, type=item.type.value)
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
            items = await self._store.search(query, limit=lim, types=type_vals)
        else:
            items = await self._store.list_recent(limit=lim)

        # Touch access stats
        now = utcnow_iso()
        for item in items:
            await self._store.update_fields(
                item.id,
                {"last_accessed_at": now, "access_count": item.access_count + 1},
            )
        return items

    async def get(self, memory_id: str) -> MemoryItem | None:
        return await self._store.get(memory_id)

    async def update(self, memory_id: str, **fields: Any) -> MemoryItem:
        item = await self._store.update_fields(memory_id, fields)
        if item is None:
            raise KeyError(f"Memory not found: {memory_id}")
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
        return ok

    async def consolidate(self) -> ConsolidationReport:
        expired = await self._store.expire_due()
        # Basic promotion: high-importance short_term → long_term
        promoted = 0
        shorts = await self._store.search("", limit=100, types=[MemoryType.SHORT_TERM.value])
        # search with empty uses recent — handle directly
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

        report = ConsolidationReport(
            expired=expired,
            promoted=promoted,
            merged=0,
            message=f"expired={expired} promoted={promoted}",
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


class MemoryModule(BaseModule):
    name = "memory"
    version = "0.1.0"
    is_critical = True

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._system: SQLiteMemorySystem | None = None

    async def _on_initialize(self) -> None:
        db = self.container.resolve(Database)
        events = self.container.resolve(EventBus)  # type: ignore[type-abstract]
        settings = self.container.resolve(Settings)
        store = MemoryStore(db)
        self._system = SQLiteMemorySystem(store, events, settings)
        self.container.register_instance(MemorySystem, self._system)  # type: ignore[type-abstract]
        self.container.register_instance(SQLiteMemorySystem, self._system)

    async def _on_start(self) -> None:
        settings = self.container.resolve(Settings)
        scheduler = self.container.try_resolve(Scheduler)
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

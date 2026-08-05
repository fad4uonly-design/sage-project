"""Learning engine implementation."""

from __future__ import annotations

from typing import Any

from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.db.connection import Database
from sage.db.repository import BaseRepository
from sage.events.bus import EventBus
from sage.events.events import ConversationEvents, Event, KnowledgeEvents, MemoryEvents
from sage.learning.interfaces import LearningEngine
from sage.learning.models import Feedback, Observation, ObservationKind, Preference
from sage.logging import get_logger
from sage.memory.interfaces import MemorySystem
from sage.memory.models import MemoryItem, MemoryType
from sage.utils.time import utcnow_iso

log = get_logger(__name__)


class DefaultLearningEngine(BaseRepository):
    def __init__(
        self,
        db: Database,
        events: EventBus,
        memory: MemorySystem | None = None,
    ) -> None:
        super().__init__(db)
        self._events = events
        self._memory = memory
        self._observation_count = 0

    def bind_memory(self, memory: MemorySystem) -> None:
        self._memory = memory

    async def observe(self, observation: Observation) -> None:
        self._observation_count += 1
        log.debug("learning.observe", kind=observation.kind.value, id=observation.id)

        # Persist notable observations into memory
        if self._memory and observation.kind in {
            ObservationKind.CORRECTION,
            ObservationKind.SUCCESS,
            ObservationKind.MISTAKE,
            ObservationKind.FEEDBACK,
        }:
            importance = {
                ObservationKind.CORRECTION: 0.8,
                ObservationKind.MISTAKE: 0.7,
                ObservationKind.SUCCESS: 0.6,
                ObservationKind.FEEDBACK: 0.65,
            }.get(observation.kind, 0.5)
            await self._memory.store(
                MemoryItem(
                    type=MemoryType.EPISODIC,
                    content=observation.content,
                    importance=importance,
                    confidence=0.7,
                    source="learning",
                    source_ref=observation.id,
                    tags=["learning", observation.kind.value],
                    metadata=dict(observation.metadata),
                )
            )

    async def learn_preference(
        self,
        key: str,
        value: Any,
        *,
        confidence: float = 0.5,
        source: str = "learned",
    ) -> None:
        pref = Preference(key=key, value=value, confidence=confidence, source=source)
        await self.db.execute(
            """
            INSERT INTO preferences (key, value, confidence, source, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                confidence = excluded.confidence,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            (pref.key, self.dumps(pref.value), pref.confidence, pref.source, pref.updated_at),
        )
        if self._memory:
            await self._memory.store(
                MemoryItem(
                    type=MemoryType.PREFERENCE,
                    content=f"Preference {key} = {value!r}",
                    importance=min(1.0, 0.4 + confidence * 0.6),
                    confidence=confidence,
                    source="learning",
                    tags=["preference", key],
                    metadata={"key": key, "value": value},
                )
            )
        log.info("learning.preference", key=key, confidence=confidence, source=source)

    async def get_preference(self, key: str) -> Preference | None:
        row = await self.db.fetchone("SELECT * FROM preferences WHERE key = ?", (key,))
        if row is None:
            return None
        return Preference(
            key=row["key"],
            value=self.loads(row["value"]),
            confidence=row["confidence"],
            source=row["source"],
            updated_at=row["updated_at"],
        )

    async def refine(self, feedback: Feedback) -> None:
        await self.observe(
            Observation(
                kind=ObservationKind.FEEDBACK,
                content=feedback.comment or f"feedback on {feedback.target}: {feedback.rating}",
                metadata={
                    "target": feedback.target,
                    "rating": feedback.rating,
                    **feedback.metadata,
                },
            )
        )
        # Adjust preference confidence if target looks like a pref key
        pref = await self.get_preference(feedback.target)
        if pref is not None:
            delta = 0.05 * feedback.rating
            new_conf = max(0.0, min(1.0, pref.confidence + delta))
            await self.learn_preference(
                pref.key, pref.value, confidence=new_conf, source=pref.source
            )

    async def count_preferences(self) -> int:
        val = await self.db.scalar("SELECT COUNT(*) FROM preferences")
        return int(val or 0)


class LearningModule(BaseModule):
    name = "learning"
    version = "0.1.0"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._engine: DefaultLearningEngine | None = None
        self._subs: list[Any] = []

    async def _on_initialize(self) -> None:
        db = self.container.resolve(Database)
        events = self.container.resolve(EventBus)  # type: ignore[type-abstract]
        memory = self.container.try_resolve(MemorySystem)  # type: ignore[type-abstract]
        self._engine = DefaultLearningEngine(db, events, memory)
        self.container.register_instance(LearningEngine, self._engine)  # type: ignore[type-abstract]
        self.container.register_instance(DefaultLearningEngine, self._engine)

        # Event-driven learning hooks
        async def on_turn(event: Event) -> None:
            payload = event.payload
            content = payload.get("user_message") or payload.get("summary") or ""
            if content and self._engine:
                await self._engine.observe(
                    Observation(
                        kind=ObservationKind.CONVERSATION,
                        content=str(content)[:2000],
                        metadata={"session_id": payload.get("session_id")},
                    )
                )

        async def on_ingest(event: Event) -> None:
            if self._engine:
                await self._engine.observe(
                    Observation(
                        kind=ObservationKind.DOCUMENT,
                        content=f"Ingested document {event.payload.get('id')}",
                        metadata=dict(event.payload),
                    )
                )

        async def on_memory(event: Event) -> None:
            # no-op placeholder for pattern mining later
            return None

        self._subs = [
            events.subscribe(ConversationEvents.TURN_COMPLETED, on_turn),
            events.subscribe(KnowledgeEvents.INGESTED, on_ingest),
            events.subscribe(MemoryEvents.CREATED, on_memory),
        ]

    async def _on_shutdown(self) -> None:
        events = self.container.try_resolve(EventBus)  # type: ignore[type-abstract]
        if events:
            for sub in self._subs:
                events.unsubscribe(sub)
        self._subs.clear()

    async def _on_health(self) -> HealthStatus | None:
        if self._engine is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        n = await self._engine.count_preferences()
        return HealthStatus.healthy(
            self.name,
            "ok",
            preferences=n,
            observations=self._engine._observation_count,
        )

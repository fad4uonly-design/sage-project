"""Learning engine — patterns, confidence refinement, workflow hints, graph suggestions."""

from __future__ import annotations

import hashlib
import re
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
from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso

log = get_logger(__name__)


class DefaultLearningEngine(BaseRepository):
    def __init__(
        self,
        db: Database,
        events: EventBus,
        memory: MemorySystem | None = None,
        container: Any | None = None,
    ) -> None:
        super().__init__(db)
        self._events = events
        self._memory = memory
        self._container = container
        self._observation_count = 0

    def bind_memory(self, memory: MemorySystem) -> None:
        self._memory = memory

    async def observe(self, observation: Observation) -> None:
        self._observation_count += 1
        log.debug("learning.observe", kind=observation.kind.value, id=observation.id)

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

        # Pattern detection on conversational / document text
        if observation.kind in {
            ObservationKind.CONVERSATION,
            ObservationKind.DOCUMENT,
            ObservationKind.SUCCESS,
        }:
            await self._detect_patterns(observation.content, observation.kind.value)

        # Suggest graph relationships from corrections / facts
        if observation.kind in {ObservationKind.CORRECTION, ObservationKind.DOCUMENT}:
            await self._suggest_graph_links(observation.content)

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
        pref = await self.get_preference(feedback.target)
        if pref is not None:
            delta = 0.05 * feedback.rating
            new_conf = max(0.0, min(1.0, pref.confidence + delta))
            await self.learn_preference(
                pref.key, pref.value, confidence=new_conf, source=pref.source
            )

        # Track correction patterns
        if feedback.rating < 0:
            await self._upsert_pattern(
                "correction",
                feedback.target or "general",
                f"Negative feedback on {feedback.target}: {feedback.comment or feedback.rating}",
                example=feedback.comment,
                confidence_delta=0.05,
            )
        elif feedback.rating > 0:
            await self._upsert_pattern(
                "success",
                feedback.target or "general",
                f"Positive feedback on {feedback.target}",
                example=feedback.comment,
                confidence_delta=0.04,
            )

    async def find_patterns(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        q = f"%{query.strip()}%"
        rows = await self.db.fetchall(
            """
            SELECT * FROM learned_patterns
            WHERE description LIKE ? OR signature LIKE ?
            ORDER BY confidence DESC, count DESC
            LIMIT ?
            """,
            (q, q, limit),
        )
        return [self._row_to_pattern(r) for r in rows]

    async def list_patterns(self, *, pattern_type: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        if pattern_type:
            rows = await self.db.fetchall(
                """
                SELECT * FROM learned_patterns WHERE pattern_type = ?
                ORDER BY confidence DESC LIMIT ?
                """,
                (pattern_type, limit),
            )
        else:
            rows = await self.db.fetchall(
                "SELECT * FROM learned_patterns ORDER BY confidence DESC LIMIT ?",
                (limit,),
            )
        return [self._row_to_pattern(r) for r in rows]

    async def count_preferences(self) -> int:
        val = await self.db.scalar("SELECT COUNT(*) FROM preferences")
        return int(val or 0)

    async def count_patterns(self) -> int:
        val = await self.db.scalar("SELECT COUNT(*) FROM learned_patterns")
        return int(val or 0)

    # --- pattern internals ---

    async def _detect_patterns(self, content: str, kind: str) -> None:
        lower = content.lower()
        # Workflow-like sequences
        if re.search(r"\b(every day|daily|each morning|weekly|every week)\b", lower):
            sig = "recurring_schedule"
            await self._upsert_pattern(
                "workflow",
                sig,
                f"User refers to recurring schedule: {content[:160]}",
                example=content[:200],
            )
        # Preference linguistic cues
        if re.search(r"\b(i (prefer|like|want|always|never))\b", lower):
            sig = hashlib.sha256(content.lower().encode()).hexdigest()[:16]
            await self._upsert_pattern(
                "preference_cue",
                sig,
                f"Preference cue: {content[:160]}",
                example=content[:200],
            )
        # Domain recurrence
        for domain, kws in (
            ("agriculture", ("crop", "farm", "soil", "irrigation", "harvest")),
            ("finance", ("budget", "invoice", "revenue", "profit")),
            ("programming", ("code", "function", "bug", "api", "python")),
            ("marketing", ("campaign", "branding", "segmentation", "positioning")),
            ("sales", ("pipeline", "quota", "forecast", "leads")),
            ("operations", ("inventory", "procurement", "logistics", "process")),
            ("accounting", ("ledger", "journal", "ratio", "balance sheet")),
            ("strategy", ("swot", "competitive", "strategic", "positioning")),
            ("analytics", ("kpi", "dashboard", "metrics", "trend")),
        ):
            if sum(1 for k in kws if k in lower) >= 2:
                await self._upsert_pattern(
                    "domain_interest",
                    domain,
                    f"Recurring interest in {domain}",
                    example=content[:200],
                    confidence_delta=0.03,
                )
        # Business workflow usage signals
        for wf_kw in (
            "business plan",
            "marketing plan",
            "sales forecast",
            "break-even",
            "kpi dashboard",
            "feasibility",
        ):
            if wf_kw in lower:
                await self._upsert_pattern(
                    "workflow_usage",
                    wf_kw.replace(" ", "_"),
                    f"User engaged workflow theme: {wf_kw}",
                    example=content[:200],
                    confidence_delta=0.04,
                )

    async def _suggest_graph_links(self, content: str) -> None:
        if not self._container:
            return
        from sage.knowledge.graph.interfaces import KnowledgeGraph

        kg = self._container.try_resolve(KnowledgeGraph)
        if not kg:
            return
        try:
            result = await kg.extract_and_merge(content, source="learning", source_ref="pattern")
            if result.edges:
                log.debug("learning.graph_suggestions", edges=len(result.edges))
        except Exception:
            log.exception("learning.graph_suggest_failed")

    async def _upsert_pattern(
        self,
        pattern_type: str,
        signature: str,
        description: str,
        *,
        example: str | None = None,
        confidence_delta: float = 0.05,
    ) -> None:
        row = await self.db.fetchone(
            "SELECT * FROM learned_patterns WHERE pattern_type = ? AND signature = ?",
            (pattern_type, signature),
        )
        now = utcnow_iso()
        if row:
            examples = self.loads(row["examples"], [])
            if example and example not in examples:
                examples = (examples + [example])[-10:]
            new_conf = min(0.95, float(row["confidence"]) + confidence_delta)
            await self.db.execute(
                """
                UPDATE learned_patterns SET
                    count = count + 1,
                    confidence = ?,
                    description = ?,
                    examples = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (new_conf, description, self.dumps(examples), now, row["id"]),
            )
        else:
            examples = [example] if example else []
            await self.db.execute(
                """
                INSERT INTO learned_patterns
                    (id, pattern_type, signature, description, count, confidence, examples, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?, '{}', ?, ?)
                """,
                (
                    new_id("pat"),
                    pattern_type,
                    signature,
                    description,
                    0.3,
                    self.dumps(examples),
                    now,
                    now,
                ),
            )

    def _row_to_pattern(self, row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "pattern_type": row["pattern_type"],
            "signature": row["signature"],
            "description": row["description"],
            "count": row["count"],
            "confidence": row["confidence"],
            "examples": self.loads(row["examples"], []),
        }


class LearningModule(BaseModule):
    name = "learning"
    version = "0.2.0"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._engine: DefaultLearningEngine | None = None
        self._subs: list[Any] = []

    async def _on_initialize(self) -> None:
        db = self.container.resolve(Database)
        events = self.container.resolve(EventBus)
        memory = self.container.try_resolve(MemorySystem)
        self._engine = DefaultLearningEngine(db, events, memory, container=self.container)
        self.container.register_instance(LearningEngine, self._engine)
        self.container.register_instance(DefaultLearningEngine, self._engine)

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
                        content=f"Ingested document {event.payload.get('id')} category={event.payload.get('category')}",
                        metadata=dict(event.payload),
                    )
                )

        async def on_memory(event: Event) -> None:
            return None

        self._subs = [
            events.subscribe(ConversationEvents.TURN_COMPLETED, on_turn),
            events.subscribe(KnowledgeEvents.INGESTED, on_ingest),
            events.subscribe(MemoryEvents.CREATED, on_memory),
        ]

    async def _on_shutdown(self) -> None:
        events = self.container.try_resolve(EventBus)
        if events:
            for sub in self._subs:
                events.unsubscribe(sub)
        self._subs.clear()

    async def _on_health(self) -> HealthStatus | None:
        if self._engine is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        n = await self._engine.count_preferences()
        p = await self._engine.count_patterns()
        return HealthStatus.healthy(
            self.name,
            "ok",
            preferences=n,
            patterns=p,
            observations=self._engine._observation_count,
        )

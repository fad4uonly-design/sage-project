"""Base event types and well-known system event names."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso


@dataclass(slots=True)
class Event:
    """Immutable-ish domain event envelope."""

    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "system"
    event_id: str = field(default_factory=lambda: new_id("event"))
    timestamp: str = field(default_factory=utcnow_iso)
    correlation_id: str | None = None

    def with_correlation(self, correlation_id: str) -> Event:
        return Event(
            type=self.type,
            payload=dict(self.payload),
            source=self.source,
            event_id=self.event_id,
            timestamp=self.timestamp,
            correlation_id=correlation_id,
        )


EventHandler = Callable[[Event], Awaitable[None] | None]


class SystemEvents:
    """Well-known system event type constants."""

    READY = "system.ready"
    SHUTTING_DOWN = "system.shutting_down"
    HEALTH_DEGRADED = "system.health.degraded"
    HEALTH_RECOVERED = "system.health.recovered"
    MODULE_INITIALIZED = "system.module.initialized"
    MODULE_FAILED = "system.module.failed"
    ERROR = "system.error"


class MemoryEvents:
    CREATED = "memory.item.created"
    UPDATED = "memory.item.updated"
    FORGOTTEN = "memory.item.forgotten"
    CONSOLIDATED = "memory.consolidated"


class KnowledgeEvents:
    INGESTED = "knowledge.document.ingested"
    INDEXED = "knowledge.document.indexed"
    RELATED = "knowledge.relation.created"


class ConversationEvents:
    SESSION_STARTED = "conversation.session.started"
    TURN_COMPLETED = "conversation.turn.completed"
    SESSION_ENDED = "conversation.session.ended"


class AgentEvents:
    TASK_STARTED = "agent.task.started"
    TASK_COMPLETED = "agent.task.completed"
    TASK_FAILED = "agent.task.failed"

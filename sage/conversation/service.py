"""Conversation module."""

from __future__ import annotations

from sage.config.settings import Settings
from sage.conversation.engine import DefaultConversationEngine
from sage.conversation.interfaces import ConversationEngine
from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.db.connection import Database
from sage.events.bus import EventBus


class ConversationModule(BaseModule):
    name = "conversation"
    version = "0.1.0"
    is_critical = True

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._engine: DefaultConversationEngine | None = None

    async def _on_initialize(self) -> None:
        db = self.container.resolve(Database)
        events = self.container.resolve(EventBus)  # type: ignore[type-abstract]
        settings = self.container.resolve(Settings)
        self._engine = DefaultConversationEngine(db, events, settings, self.container)
        self.container.register_instance(ConversationEngine, self._engine)  # type: ignore[type-abstract]
        self.container.register_instance(DefaultConversationEngine, self._engine)

    async def _on_health(self) -> HealthStatus | None:
        if self._engine is None:
            return HealthStatus.unhealthy(self.name, "not initialized", critical=True)
        return HealthStatus.healthy(
            self.name,
            "ok",
            active_sessions=len(self._engine._sessions),
        )

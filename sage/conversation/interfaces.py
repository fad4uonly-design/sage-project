"""Conversation engine protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from sage.conversation.models import ConversationTurn, Session


@runtime_checkable
class ConversationEngine(Protocol):
    async def start_session(self, *, user_id: str = "default") -> Session: ...

    async def respond(self, session_id: str, message: str) -> ConversationTurn: ...

    async def end_session(self, session_id: str) -> None: ...

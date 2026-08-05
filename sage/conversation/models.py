"""Conversation domain models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso


class Session(BaseModel):
    id: str = Field(default_factory=lambda: new_id("session"))
    user_id: str = "default"
    started_at: str = Field(default_factory=utcnow_iso)
    ended_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationTurn(BaseModel):
    id: str = Field(default_factory=lambda: new_id("turn"))
    session_id: str
    turn_index: int
    user_message: str
    assistant_message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utcnow_iso)

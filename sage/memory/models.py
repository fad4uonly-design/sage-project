"""Memory domain models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso


class MemoryType(StrEnum):
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PREFERENCE = "preference"
    PROJECT = "project"
    TECHNICAL = "technical"
    RELATIONSHIP = "relationship"
    FACT = "fact"


class MemoryItem(BaseModel):
    id: str = Field(default_factory=lambda: new_id("memory"))
    type: MemoryType = MemoryType.FACT
    content: str
    summary: str | None = None
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source: str | None = None
    source_ref: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    embedding_id: str | None = None
    content_hash: str | None = None
    version: int = 1
    created_at: str = Field(default_factory=utcnow_iso)
    updated_at: str = Field(default_factory=utcnow_iso)
    last_accessed_at: str | None = None
    access_count: int = 0
    expires_at: str | None = None
    deleted_at: str | None = None


class MemoryRelation(BaseModel):
    id: str = Field(default_factory=lambda: new_id("mrel"))
    source_id: str
    target_id: str
    relation: str
    weight: float = 1.0
    confidence: float = 0.5
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utcnow_iso)


class ConsolidationReport(BaseModel):
    merged: int = 0
    expired: int = 0
    promoted: int = 0
    related: int = 0
    rescored: int = 0
    message: str = ""

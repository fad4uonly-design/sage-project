"""Knowledge domain models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso


class DocumentStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    ERROR = "error"


class DocumentRef(BaseModel):
    id: str = Field(default_factory=lambda: new_id("document"))
    path: str
    title: str | None = None
    media_type: str | None = None
    category: str | None = None
    checksum: str | None = None
    size_bytes: int | None = None
    status: DocumentStatus = DocumentStatus.PENDING
    summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    ingested_at: str = Field(default_factory=utcnow_iso)


class KnowledgeHit(BaseModel):
    document_id: str
    chunk_id: str | None = None
    title: str | None = None
    snippet: str
    score: float = 0.0
    category: str | None = None
    path: str | None = None


class KnowledgeChunk(BaseModel):
    id: str = Field(default_factory=lambda: new_id("chunk"))
    document_id: str
    chunk_index: int
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)

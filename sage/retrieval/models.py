"""Retrieval result models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from sage.utils.time import utcnow_iso


class RetrievalLayer(StrEnum):
    MEMORY = "memory"
    KNOWLEDGE_GRAPH = "knowledge_graph"
    DOCUMENT = "document"
    SEMANTIC = "semantic"
    PATTERN = "pattern"


class EvidenceItem(BaseModel):
    layer: RetrievalLayer
    content: str
    score: float = 0.0
    confidence: float = 0.5
    source_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalResult(BaseModel):
    query: str
    items: list[EvidenceItem] = Field(default_factory=list)
    ranked: list[EvidenceItem] = Field(default_factory=list)
    memories: list[str] = Field(default_factory=list)
    graph_facts: list[str] = Field(default_factory=list)
    documents: list[str] = Field(default_factory=list)
    overall_confidence: float = 0.0
    explanation: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utcnow_iso)

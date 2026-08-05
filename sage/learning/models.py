"""Learning domain models."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso


class ObservationKind(str, Enum):
    CONVERSATION = "conversation"
    DOCUMENT = "document"
    CORRECTION = "correction"
    SUCCESS = "success"
    MISTAKE = "mistake"
    EXTERNAL = "external"
    FEEDBACK = "feedback"


class Observation(BaseModel):
    id: str = Field(default_factory=lambda: new_id("observation"))
    kind: ObservationKind
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utcnow_iso)


class Preference(BaseModel):
    key: str
    value: Any
    confidence: float = 0.5
    source: str = "learned"  # learned | explicit
    updated_at: str = Field(default_factory=utcnow_iso)


class Feedback(BaseModel):
    target: str
    rating: float = Field(ge=-1.0, le=1.0)
    comment: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

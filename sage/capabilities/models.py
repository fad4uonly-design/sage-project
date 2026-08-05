"""Capability descriptor models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso


class CapabilityDescriptor(BaseModel):
    id: str = Field(default_factory=lambda: new_id("cap"))
    principal: str
    principal_type: str = "agent"  # agent | tool | plugin
    domain: str
    capabilities: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    reasoning_strategies: list[str] = Field(default_factory=list)
    confidence_threshold: float = Field(default=0.4, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    created_at: str = Field(default_factory=utcnow_iso)
    updated_at: str = Field(default_factory=utcnow_iso)

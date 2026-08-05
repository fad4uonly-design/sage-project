"""Capability profile attached to every domain agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AgentCapabilityProfile(BaseModel):
    """
    Declares what an agent is, what it can do, and how it thinks.

    Mirrors Capability Registry entries and is used for dispatch + collaboration.
    """

    principal: str
    domain: str
    display_name: str
    description: str = ""
    capabilities: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    reasoning_strategies: list[str] = Field(default_factory=list)
    workflows: list[str] = Field(default_factory=list)
    collaborate_with: list[str] = Field(default_factory=list)  # domains
    confidence_threshold: float = 0.35

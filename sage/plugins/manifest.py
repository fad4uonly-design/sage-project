"""Plugin manifest schema — supports agents, skills, tools, workflows (v0.4.0)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PluginManifest(BaseModel):
    id: str
    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    entrypoint: str = "plugin:Plugin"
    permissions: list[str] = Field(default_factory=list)
    enabled: bool = True
    # Extension declarations (optional — plugin can also register in on_load)
    agents: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    workflows: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

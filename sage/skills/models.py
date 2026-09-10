"""Skill Library domain models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso


class SkillCategory(StrEnum):
    ANALYSIS = "analysis"
    PLANNING = "planning"
    REPORTING = "reporting"
    COMMUNICATION = "communication"
    DECISION = "decision"
    RESEARCH = "research"
    DOMAIN = "domain"
    UTILITY = "utility"


class SkillManifest(BaseModel):
    """Declarative description of a skill for discovery and capability registry."""

    id: str
    name: str
    category: SkillCategory
    description: str = ""
    version: str = "1.0.0"
    # Domains that commonly use this skill (empty = universal)
    domains: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    # Optional required permissions (checked via PermissionManager when present)
    permissions: list[str] = Field(default_factory=list)
    # Parameter schema (lightweight JSON-schema-ish dict)
    parameters_schema: dict[str, Any] = Field(default_factory=dict)
    examples: list[str] = Field(default_factory=list)


class SkillRequest(BaseModel):
    skill_id: str
    task: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    principal: str = "core"
    request_id: str = Field(default_factory=lambda: new_id("skreq"))


class SkillResult(BaseModel):
    skill_id: str
    success: bool
    output: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    request_id: str | None = None
    created_at: str = Field(default_factory=utcnow_iso)

    def format(self) -> str:
        if not self.success:
            return f"**Skill `{self.skill_id}` failed:** {self.error or 'unknown error'}"
        parts = [f"**Skill:** {self.skill_id}", ""]
        if self.output:
            parts.append(self.output)
        if self.steps:
            parts.append("")
            parts.append("**Skill steps:**")
            for s in self.steps:
                title = s.get("title") or s.get("id") or "step"
                parts.append(f"- {title} [{s.get('status', 'done')}]")
        if self.evidence:
            parts.append("")
            parts.append("**Evidence:**")
            for e in self.evidence[:8]:
                parts.append(f"- {e}")
        parts.append("")
        parts.append(f"_Confidence: {self.confidence:.2f}_")
        return "\n".join(parts)

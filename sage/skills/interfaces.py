"""Skill Library protocols."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from sage.skills.models import SkillCategory, SkillManifest, SkillRequest, SkillResult


@runtime_checkable
class Skill(Protocol):
    @property
    def manifest(self) -> SkillManifest: ...

    def match_score(self, text: str, *, domain: str | None = None) -> float:
        """0..1 how well this skill fits the text/domain."""
        ...

    async def execute(self, request: SkillRequest) -> SkillResult: ...


@runtime_checkable
class SkillLibrary(Protocol):
    def register(self, skill: Skill) -> None: ...

    def get(self, skill_id: str) -> Skill | None: ...

    def list_skills(
        self,
        *,
        category: SkillCategory | str | None = None,
        domain: str | None = None,
    ) -> list[SkillManifest]: ...

    def match(
        self,
        text: str,
        *,
        domain: str | None = None,
        category: SkillCategory | str | None = None,
        limit: int = 5,
    ) -> list[tuple[Skill, float]]: ...

    async def invoke(
        self,
        skill_id: str,
        *,
        task: str = "",
        params: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        principal: str = "core",
    ) -> SkillResult: ...

    async def invoke_best(
        self,
        task: str,
        *,
        domain: str | None = None,
        category: SkillCategory | str | None = None,
        context: dict[str, Any] | None = None,
        principal: str = "core",
        min_score: float = 0.25,
    ) -> SkillResult | None: ...

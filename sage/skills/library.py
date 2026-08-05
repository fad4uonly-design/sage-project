"""In-process Skill Library implementation."""

from __future__ import annotations

from typing import Any

from sage.logging import get_logger
from sage.skills.interfaces import Skill, SkillLibrary
from sage.skills.models import SkillCategory, SkillManifest, SkillRequest, SkillResult

log = get_logger(__name__)


class DefaultSkillLibrary:
    """
    Shared registry of reusable skills.

    Agents orchestrate skills instead of re-implementing SWOT, planning,
    reporting, decision framing, etc.
    """

    def __init__(self, permission_manager: Any | None = None) -> None:
        self._skills: dict[str, Skill] = {}
        self._permissions = permission_manager

    def register(self, skill: Skill) -> None:
        mid = skill.manifest.id
        self._skills[mid] = skill
        log.debug(
            "skills.registered",
            id=mid,
            category=skill.manifest.category.value,
            name=skill.manifest.name,
        )

    def get(self, skill_id: str) -> Skill | None:
        return self._skills.get(skill_id)

    def list_skills(
        self,
        *,
        category: SkillCategory | str | None = None,
        domain: str | None = None,
    ) -> list[SkillManifest]:
        cat = None
        if category is not None:
            cat = category if isinstance(category, SkillCategory) else SkillCategory(category)
        out: list[SkillManifest] = []
        for skill in self._skills.values():
            m = skill.manifest
            if cat and m.category != cat:
                continue
            if domain and m.domains and domain not in m.domains and "shared" not in m.domains:
                # Universal skills have empty domains list
                if m.domains:
                    continue
            out.append(m)
        return sorted(out, key=lambda x: (x.category.value, x.name))

    def match(
        self,
        text: str,
        *,
        domain: str | None = None,
        category: SkillCategory | str | None = None,
        limit: int = 5,
    ) -> list[tuple[Skill, float]]:
        cat = None
        if category is not None:
            cat = category if isinstance(category, SkillCategory) else SkillCategory(category)
        scored: list[tuple[Skill, float]] = []
        for skill in self._skills.values():
            if cat and skill.manifest.category != cat:
                continue
            score = skill.match_score(text, domain=domain)
            if score > 0:
                scored.append((skill, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    async def invoke(
        self,
        skill_id: str,
        *,
        task: str = "",
        params: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        principal: str = "core",
    ) -> SkillResult:
        skill = self._skills.get(skill_id)
        if skill is None:
            return SkillResult(
                skill_id=skill_id,
                success=False,
                error=f"Unknown skill: {skill_id}",
            )

        # Permission gate
        for perm in skill.manifest.permissions:
            if self._permissions is not None:
                try:
                    await self._permissions.require(principal, perm)
                except Exception as exc:
                    return SkillResult(
                        skill_id=skill_id,
                        success=False,
                        error=str(exc),
                    )

        request = SkillRequest(
            skill_id=skill_id,
            task=task,
            params=dict(params or {}),
            context=dict(context or {}),
            principal=principal,
        )
        try:
            result = await skill.execute(request)
            result.request_id = request.request_id
            log.info(
                "skills.invoked",
                skill_id=skill_id,
                success=result.success,
                principal=principal,
            )
            return result
        except Exception as exc:
            log.exception("skills.invoke_failed", skill_id=skill_id)
            return SkillResult(skill_id=skill_id, success=False, error=str(exc))

    async def invoke_best(
        self,
        task: str,
        *,
        domain: str | None = None,
        category: SkillCategory | str | None = None,
        context: dict[str, Any] | None = None,
        principal: str = "core",
        min_score: float = 0.25,
    ) -> SkillResult | None:
        matches = self.match(task, domain=domain, category=category, limit=1)
        if not matches or matches[0][1] < min_score:
            return None
        skill, score = matches[0]
        result = await self.invoke(
            skill.manifest.id,
            task=task,
            context=context,
            principal=principal,
        )
        result.data = {**result.data, "match_score": score}
        return result

    def count(self) -> int:
        return len(self._skills)

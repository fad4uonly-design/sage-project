"""Base helpers for implementing skills."""

from __future__ import annotations

import re
from typing import Any

from sage.skills.models import SkillCategory, SkillManifest, SkillRequest, SkillResult


class BaseSkill:
    """Convenience base — subclasses set `manifest` and implement `run`."""

    manifest: SkillManifest

    def match_score(self, text: str, *, domain: str | None = None) -> float:
        lower = text.lower()
        score = 0.0
        name = self.manifest.name.lower()
        if name in lower or self.manifest.id.replace("_", " ") in lower:
            score += 0.5
        hits = sum(1 for t in self.manifest.tags if t.lower() in lower)
        if self.manifest.tags:
            score += min(0.5, hits / max(len(self.manifest.tags), 1) * 0.8)
        if domain and self.manifest.domains:
            if domain in self.manifest.domains or "shared" in self.manifest.domains:
                score += 0.1
        elif not self.manifest.domains:
            score += 0.05  # universal slight prior
        return min(1.0, score)

    async def execute(self, request: SkillRequest) -> SkillResult:
        try:
            return await self.run(request)
        except Exception as exc:
            return SkillResult(
                skill_id=self.manifest.id,
                success=False,
                error=str(exc),
                request_id=request.request_id,
            )

    async def run(self, request: SkillRequest) -> SkillResult:
        raise NotImplementedError

    # --- helpers for subclasses ---

    @staticmethod
    def _task(request: SkillRequest) -> str:
        return request.task or str(request.params.get("task") or "")

    @staticmethod
    def _ctx_list(request: SkillRequest, key: str) -> list[str]:
        val = request.context.get(key) or []
        return list(val) if isinstance(val, list) else []

    @staticmethod
    def _num(text: str, default: float = 0.0) -> float:
        m = re.search(r"(\d+(?:\.\d+)?)", text.replace(",", ""))
        return float(m.group(1)) if m else default

    def _ok(
        self,
        output: str,
        *,
        steps: list[dict[str, Any]] | None = None,
        data: dict[str, Any] | None = None,
        evidence: list[str] | None = None,
        confidence: float = 0.7,
        request: SkillRequest | None = None,
    ) -> SkillResult:
        return SkillResult(
            skill_id=self.manifest.id,
            success=True,
            output=output,
            steps=steps or [],
            data=data or {},
            evidence=evidence or [],
            confidence=confidence,
            request_id=request.request_id if request else None,
        )

"""Shared base for Business Intelligence advisors."""

from __future__ import annotations

from typing import Any

from sage.agents.domain_base import DomainAgent
from sage.agents.profile import AgentCapabilityProfile


class BusinessAdvisor(DomainAgent):
    """
    Base for all BI suite advisors.

    Extends DomainAgent with business-suite defaults:
    collaboration within the suite + finance/agriculture/programming,
    and business-oriented graph enrichment.
    """

    suite_name: str = "business_intelligence"

    async def enrich_domain_context(self, task: Any, ctx: dict[str, Any]) -> None:
        kg = ctx.get("kg")
        if not kg:
            return
        try:
            await kg.extract_and_merge(
                task.description,
                source=self.profile.principal,
                source_ref=f"bi:{self.profile.domain}",
            )
        except Exception:
            pass

    def select_strategy(self, task: Any, ctx: dict[str, Any]) -> str | None:
        prefs = self.profile.reasoning_strategies
        desc = task.description.lower()
        if any(w in desc for w in ("risk", "compliance", "threat", "hazard")):
            return "risk"
        if any(w in desc for w in ("decide", "choose", "which", "compare", "vs")):
            return "decision"
        if any(w in desc for w in ("plan", "schedule", "roadmap", "milestone")):
            return "planning"
        if any(w in desc for w in ("calculate", "ratio", "percent", "margin", "break-even")):
            return "mathematical"
        return prefs[0] if prefs else "business"


def bi_profile(
    *,
    principal: str,
    domain: str,
    display_name: str,
    description: str,
    capabilities: list[str],
    workflows: list[str],
    reasoning_strategies: list[str] | None = None,
    collaborate_with: list[str] | None = None,
    tools: list[str] | None = None,
) -> AgentCapabilityProfile:
    """Factory for BI capability profiles with sensible suite defaults."""
    default_collab = [
        "business",
        "marketing",
        "sales",
        "operations",
        "finance",
        "accounting",
        "hr",
        "project_management",
        "market_research",
        "analytics",
        "risk_compliance",
        "strategy",
        "agriculture",
        "programming",
        "planning",
    ]
    collab = list(dict.fromkeys((collaborate_with or []) + default_collab))
    # Don't collaborate with self domain
    collab = [c for c in collab if c != domain]
    return AgentCapabilityProfile(
        principal=principal,
        domain=domain,
        display_name=display_name,
        description=description,
        capabilities=capabilities,
        tools=tools or ["calculator", "current_time"],
        permissions=["memory.read", "memory.write"],
        reasoning_strategies=reasoning_strategies
        or ["business", "decision", "planning", "risk"],
        workflows=workflows,
        collaborate_with=collab,
        confidence_threshold=0.3,
    )

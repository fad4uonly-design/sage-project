"""Decision engine models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso


class Criterion(BaseModel):
    id: str
    name: str
    weight: float = Field(default=1.0, ge=0.0)
    maximize: bool = True  # False = lower is better (cost, risk)
    description: str = ""


class DecisionOption(BaseModel):
    id: str
    name: str
    description: str = ""
    # criterion_id -> raw score (any scale; normalized internally)
    scores: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    risks: list[str] = Field(default_factory=list)


class DecisionRequest(BaseModel):
    id: str = Field(default_factory=lambda: new_id("dec"))
    question: str
    criteria: list[Criterion]
    options: list[DecisionOption]
    risk_penalty: float = Field(default=0.05, ge=0.0, le=0.5)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScoredOption(BaseModel):
    option_id: str
    name: str
    total_score: float
    normalized_scores: dict[str, float] = Field(default_factory=dict)
    weighted_scores: dict[str, float] = Field(default_factory=dict)
    risk_adjustment: float = 0.0
    rank: int = 0
    rationale: str = ""


class DecisionResult(BaseModel):
    request_id: str
    question: str
    ranking: list[ScoredOption] = Field(default_factory=list)
    recommendation: str = ""
    confidence: float = 0.0
    trade_offs: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    explanation: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utcnow_iso)

    def format(self) -> str:
        lines = [
            "### Decision Analysis",
            f"**Question:** {self.question}",
            f"**Confidence:** {self.confidence:.2f}",
            "",
            "**Ranking:**",
        ]
        for s in self.ranking:
            lines.append(
                f"{s.rank}. **{s.name}** — score {s.total_score:.3f}"
                + (f" (risk adj {s.risk_adjustment:.3f})" if s.risk_adjustment else "")
            )
            if s.rationale:
                lines.append(f"   {s.rationale}")
        lines += ["", f"**Recommendation:** {self.recommendation}"]
        if self.trade_offs:
            lines.append("")
            lines.append("**Trade-offs:**")
            for t in self.trade_offs:
                lines.append(f"- {t}")
        if self.risks:
            lines.append("")
            lines.append("**Risks:**")
            for r in self.risks:
                lines.append(f"- {r}")
        if self.explanation:
            lines.append("")
            lines.append("**Method:**")
            for e in self.explanation:
                lines.append(f"- {e}")
        return "\n".join(lines)

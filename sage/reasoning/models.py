"""Reasoning domain models."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from sage.utils.time import utcnow_iso


class StrategyKind(str, Enum):
    AUTO = "auto"
    DEDUCTION = "deduction"
    INDUCTION = "induction"
    CAUSAL = "causal"
    MULTI_STEP = "multi_step"
    DECISION = "decision"
    RISK = "risk"
    HYPOTHESIS = "hypothesis"
    LOGICAL = "logical"
    MATHEMATICAL = "mathematical"
    SCIENTIFIC = "scientific"
    BUSINESS = "business"
    AGRICULTURE = "agriculture"
    PLANNING = "planning"
    ETHICAL = "ethical"


class ReasoningStep(BaseModel):
    index: int
    thought: str
    kind: str = "analysis"
    evidence: list[str] = Field(default_factory=list)
    confidence: float = 0.5


class ReasoningContext(BaseModel):
    memories: list[str] = Field(default_factory=list)
    knowledge: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    graph_facts: list[str] = Field(default_factory=list)
    documents: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExplainabilityReport(BaseModel):
    """Full transparent chain for an important conclusion."""

    question: str
    relevant_memories: list[str] = Field(default_factory=list)
    knowledge_graph_facts: list[str] = Field(default_factory=list)
    supporting_documents: list[str] = Field(default_factory=list)
    reasoning_strategy: str = ""
    strategies_used: list[str] = Field(default_factory=list)
    confidence_score: float = 0.0
    final_answer: str = ""
    trace_summary: list[str] = Field(default_factory=list)
    retrieval_explanation: list[str] = Field(default_factory=list)

    def format(self) -> str:
        lines = [
            "### Explainable Reasoning Trace",
            f"**Question:** {self.question}",
            "",
            "**Relevant Memories:**",
        ]
        if self.relevant_memories:
            lines.extend(f"- {m}" for m in self.relevant_memories[:8])
        else:
            lines.append("- (none)")
        lines += ["", "**Knowledge Graph Facts:**"]
        if self.knowledge_graph_facts:
            lines.extend(f"- {f}" for f in self.knowledge_graph_facts[:8])
        else:
            lines.append("- (none)")
        lines += ["", "**Supporting Documents:**"]
        if self.supporting_documents:
            lines.extend(f"- {d}" for d in self.supporting_documents[:5])
        else:
            lines.append("- (none)")
        lines += [
            "",
            f"**Reasoning Strategy:** {self.reasoning_strategy}",
        ]
        if self.strategies_used:
            lines.append(f"**Strategies Used:** {', '.join(self.strategies_used)}")
        lines += [
            f"**Confidence Score:** {self.confidence_score:.2f}",
            "",
            "**Trace:**",
        ]
        for t in self.trace_summary:
            lines.append(f"- {t}")
        lines += ["", f"**Final Answer:** {self.final_answer}"]
        if self.retrieval_explanation:
            lines += ["", "**Retrieval:**"]
            lines.extend(f"- {e}" for e in self.retrieval_explanation)
        return "\n".join(lines)


class ReasoningResult(BaseModel):
    problem: str
    strategy: StrategyKind
    conclusion: str
    trace: list[ReasoningStep] = Field(default_factory=list)
    confidence: float = 0.5
    alternatives: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    strategies_used: list[str] = Field(default_factory=list)
    explainability: ExplainabilityReport | None = None
    created_at: str = Field(default_factory=utcnow_iso)

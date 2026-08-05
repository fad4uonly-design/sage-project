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
    constraints: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReasoningResult(BaseModel):
    problem: str
    strategy: StrategyKind
    conclusion: str
    trace: list[ReasoningStep] = Field(default_factory=list)
    confidence: float = 0.5
    alternatives: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utcnow_iso)

"""Built-in specialized reasoning strategies."""

from __future__ import annotations

import ast
import operator
import re
from collections.abc import Callable
from typing import Any

from sage.reasoning.models import (
    ReasoningContext,
    ReasoningResult,
    ReasoningStep,
    StrategyKind,
)
from sage.reasoning.strategies.base import StrategyRegistry


def _base_trace(problem: str, ctx: ReasoningContext) -> list[ReasoningStep]:
    trace = [
        ReasoningStep(index=0, thought=f"Understood problem: {problem}", kind="understand", confidence=0.9)
    ]
    evidence = [
        *ctx.facts[:4],
        *ctx.graph_facts[:4],
        *ctx.memories[:4],
        *ctx.knowledge[:3],
        *ctx.documents[:2],
    ]
    if evidence:
        trace.append(
            ReasoningStep(
                index=1,
                thought="Gathered evidence from memory, knowledge graph, and documents.",
                kind="gather",
                evidence=evidence[:12],
                confidence=0.75,
            )
        )
    else:
        trace.append(
            ReasoningStep(
                index=1,
                thought="Limited prior evidence; reasoning primarily from the problem statement.",
                kind="gather",
                confidence=0.4,
            )
        )
    if ctx.constraints:
        trace.append(
            ReasoningStep(
                index=2,
                thought="Constraints: " + "; ".join(ctx.constraints),
                kind="constrain",
                evidence=list(ctx.constraints),
                confidence=0.85,
            )
        )
    return trace


def _finish(
    problem: str,
    kind: StrategyKind,
    trace: list[ReasoningStep],
    analysis: str,
    conclusion: str,
    confidence: float,
    *,
    alternatives: list[str] | None = None,
    risks: list[str] | None = None,
) -> ReasoningResult:
    trace = list(trace)
    trace.append(
        ReasoningStep(
            index=len(trace),
            thought=analysis,
            kind=kind.value,
            confidence=confidence,
        )
    )
    trace.append(
        ReasoningStep(
            index=len(trace),
            thought=f"Conclusion: {conclusion}",
            kind="conclude",
            confidence=confidence,
        )
    )
    return ReasoningResult(
        problem=problem,
        strategy=kind,
        conclusion=conclusion,
        trace=trace,
        confidence=confidence,
        alternatives=alternatives or [],
        risks=risks or [],
        strategies_used=[kind.value],
    )


class _KeywordStrategy:
    kind: StrategyKind
    name: str
    domains: frozenset[str]
    keywords: tuple[str, ...]
    base_score: float = 0.3

    def suitability(self, problem: str, context: ReasoningContext) -> float:
        lower = problem.lower()
        hits = sum(1 for k in self.keywords if k in lower)
        score = self.base_score + hits * 0.15
        # Domain boost from graph facts / memories
        blob = " ".join(context.graph_facts + context.memories).lower()
        for d in self.domains:
            if d in blob or d in lower:
                score += 0.1
        return min(1.0, score)


class LogicalStrategy(_KeywordStrategy):
    kind = StrategyKind.LOGICAL
    name = "Logical Reasoning"
    domains = frozenset({"logic", "general"})
    keywords = ("if ", "therefore", "implies", "given that", "all ", "none ", "either", "must be")
    base_score = 0.25

    async def apply(self, problem: str, context: ReasoningContext, *, models: Any | None = None) -> ReasoningResult:
        trace = _base_trace(problem, context)
        premises = context.facts + context.graph_facts
        analysis = (
            "Logical analysis: identify premises, check consistency, apply inference rules "
            "(modus ponens / elimination). Reject conclusions that contradict premises."
        )
        if premises:
            conclusion = (
                f"Based on {len(premises)} premise(s), the logically supported position on "
                f"«{problem}» is to accept only what follows from the stated facts"
                f" (e.g. {premises[0][:120]}). Flag any unsupported leaps."
            )
            conf = 0.7
        else:
            conclusion = (
                f"Insufficient explicit premises for «{problem}». "
                "State assumptions clearly before drawing a firm logical conclusion."
            )
            conf = 0.45
        return _finish(problem, self.kind, trace, analysis, conclusion, conf)


class MathematicalStrategy(_KeywordStrategy):
    kind = StrategyKind.MATHEMATICAL
    name = "Mathematical Reasoning"
    domains = frozenset({"math", "finance", "engineering"})
    keywords = ("calculate", "compute", "percent", "%", "sum", "average", "equation", "how much", "ratio")
    base_score = 0.2

    _OPS: dict[type[ast.AST], Callable[..., Any]] = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
        ast.Mod: operator.mod,
    }

    async def apply(self, problem: str, context: ReasoningContext, *, models: Any | None = None) -> ReasoningResult:
        trace = _base_trace(problem, context)
        expr_match = re.search(r"([0-9\.\s\+\-\*\/\%\(\)]{3,})", problem)
        computed = None
        if expr_match:
            expr = expr_match.group(1).strip()
            try:
                tree = ast.parse(expr, mode="eval")
                computed = self._eval(tree.body)
                trace.append(
                    ReasoningStep(
                        index=len(trace),
                        thought=f"Evaluated expression `{expr}` → {computed}",
                        kind="compute",
                        confidence=0.95,
                    )
                )
            except Exception:
                computed = None
        analysis = "Mathematical approach: extract quantities, choose operations, verify units and magnitude."
        if computed is not None:
            conclusion = f"Computed result for «{problem}»: **{computed}**."
            conf = 0.9
        else:
            conclusion = (
                f"For «{problem}», define variables, write the governing equation, "
                "solve step-by-step, and sanity-check the magnitude."
            )
            conf = 0.5
        return _finish(problem, self.kind, trace, analysis, conclusion, conf)

    def _eval(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in self._OPS:
            return self._OPS[type(node.op)](self._eval(node.left), self._eval(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in self._OPS:
            return self._OPS[type(node.op)](self._eval(node.operand))
        raise ValueError("unsupported")


class ScientificStrategy(_KeywordStrategy):
    kind = StrategyKind.SCIENTIFIC
    name = "Scientific Reasoning"
    domains = frozenset({"science", "research", "agriculture", "engineering"})
    keywords = ("hypothesis", "experiment", "evidence", "observe", "theory", "test", "measure", "data")
    base_score = 0.25

    async def apply(self, problem: str, context: ReasoningContext, *, models: Any | None = None) -> ReasoningResult:
        trace = _base_trace(problem, context)
        analysis = (
            "Scientific method: observe → hypothesize → predict → test → revise. "
            "Prefer falsifiable claims and independent corroboration."
        )
        evidence = context.graph_facts + context.documents + context.facts
        conclusion = (
            f"Working hypothesis for «{problem}»: "
            + (f"supported by evidence such as «{evidence[0][:100]}». " if evidence else "needs baseline data. ")
            + "Design a minimal test that could falsify it; update confidence with results."
        )
        conf = 0.6 if evidence else 0.45
        return _finish(problem, self.kind, trace, analysis, conclusion, conf)


class BusinessStrategy(_KeywordStrategy):
    kind = StrategyKind.BUSINESS
    name = "Business Reasoning"
    domains = frozenset({"business", "finance", "marketing", "strategy"})
    keywords = (
        "revenue",
        "profit",
        "customer",
        "market",
        "roi",
        "pricing",
        "competitor",
        "business",
        "startup",
        "sales",
        "cost",
    )
    base_score = 0.25

    async def apply(self, problem: str, context: ReasoningContext, *, models: Any | None = None) -> ReasoningResult:
        trace = _base_trace(problem, context)
        analysis = (
            "Business framing: customer value, unit economics, competitive position, "
            "execution risk, and capital efficiency."
        )
        alternatives = [
            "Double down on the highest-ROI channel",
            "Run a time-boxed experiment before full commitment",
            "Cut scope to the smallest sellable wedge",
        ]
        risks = ["Market misread", "Cash runway", "Execution capacity"]
        conclusion = (
            f"For «{problem}», clarify the target customer and measurable success metric, "
            "estimate cost vs upside, and choose the option with best expected value "
            "under cash and capacity constraints. Prefer reversible bets first."
        )
        conf = 0.62 + (0.08 if context.memories or context.graph_facts else 0.0)
        return _finish(
            problem, self.kind, trace, analysis, conclusion, min(0.85, conf),
            alternatives=alternatives, risks=risks,
        )


class AgricultureStrategy(_KeywordStrategy):
    kind = StrategyKind.AGRICULTURE
    name = "Agricultural Reasoning"
    domains = frozenset({"agriculture", "farming", "crops", "livestock"})
    keywords = (
        "crop",
        "soil",
        "farm",
        "harvest",
        "irrigation",
        "greenhouse",
        "fertilizer",
        "pest",
        "blight",
        "livestock",
        "plant",
        "seed",
        "tomato",
        "yield",
    )
    base_score = 0.2

    async def apply(self, problem: str, context: ReasoningContext, *, models: Any | None = None) -> ReasoningResult:
        trace = _base_trace(problem, context)
        facts = context.graph_facts or context.knowledge or context.memories
        analysis = (
            "Agricultural analysis: climate/season window, soil & water, variety selection, "
            "pest/disease pressure, labor, and market timing."
        )
        if facts:
            trace.append(
                ReasoningStep(
                    index=len(trace),
                    thought="Applied domain facts from knowledge graph / memory.",
                    kind="domain_facts",
                    evidence=facts[:8],
                    confidence=0.8,
                )
            )
        conclusion = (
            f"For «{problem}», align the action with season and soil moisture, "
            "ensure water and nutrient balance, monitor for disease (e.g. blight), "
            "and stage work to protect yield. "
            + (f"Key fact: {facts[0][:140]}" if facts else "Gather soil and weather baselines first.")
        )
        risks = ["Weather shock", "Water shortage", "Pest/disease outbreak", "Market price swing"]
        conf = 0.68 if facts else 0.5
        return _finish(problem, self.kind, trace, analysis, conclusion, conf, risks=risks)


class PlanningStrategy(_KeywordStrategy):
    kind = StrategyKind.PLANNING
    name = "Planning Reasoning"
    domains = frozenset({"planning", "project", "general"})
    keywords = ("plan", "schedule", "roadmap", "milestone", "steps", "how to", "organize", "timeline")
    base_score = 0.3

    async def apply(self, problem: str, context: ReasoningContext, *, models: Any | None = None) -> ReasoningResult:
        trace = _base_trace(problem, context)
        analysis = "Planning decomposition: goal → constraints → work breakdown → sequence → checkpoints."
        conclusion = (
            f"Plan for «{problem}»: (1) define done, (2) list dependencies and constraints, "
            "(3) sequence high-leverage tasks first, (4) set checkpoints, (5) leave buffer for risk."
        )
        return _finish(problem, self.kind, trace, analysis, conclusion, 0.65)


class RiskStrategy(_KeywordStrategy):
    kind = StrategyKind.RISK
    name = "Risk Analysis"
    domains = frozenset({"risk", "security", "operations", "general"})
    keywords = ("risk", "danger", "fail", "hazard", "threat", "downside", "mitigate", "contingency")
    base_score = 0.35

    async def apply(self, problem: str, context: ReasoningContext, *, models: Any | None = None) -> ReasoningResult:
        trace = _base_trace(problem, context)
        analysis = "Risk matrix: identify hazards → likelihood × impact → mitigations → residual risk."
        risks = [
            "Execution failure",
            "Resource overrun",
            "External dependency failure",
            "Information incompleteness",
        ]
        conclusion = (
            f"Primary risks for «{problem}» should be mitigated with monitoring, "
            "fallback plans, staged rollout, and clear abort criteria."
        )
        return _finish(problem, self.kind, trace, analysis, conclusion, 0.66, risks=risks)


class DecisionStrategy(_KeywordStrategy):
    kind = StrategyKind.DECISION
    name = "Decision Reasoning"
    domains = frozenset({"decision", "general"})
    keywords = ("decide", "choose", "which", "option", "should i", "vs", "or not")
    base_score = 0.35

    async def apply(self, problem: str, context: ReasoningContext, *, models: Any | None = None) -> ReasoningResult:
        trace = _base_trace(problem, context)
        analysis = "Decision analysis: options × criteria × weights → expected value under constraints."
        alternatives = [
            "Option A: act now with current information",
            "Option B: gather more evidence (time-boxed)",
            "Option C: defer and monitor triggers",
        ]
        conclusion = (
            f"For «{problem}», pick the option that maximizes expected value while respecting "
            "constraints"
            + (f" ({', '.join(context.constraints)})" if context.constraints else "")
            + ". Prefer a reversible first step."
        )
        return _finish(
            problem, self.kind, trace, analysis, conclusion, 0.64,
            alternatives=alternatives,
            risks=["Incomplete information", "Irreversible commitment too early"],
        )


class EthicalStrategy(_KeywordStrategy):
    kind = StrategyKind.ETHICAL
    name = "Ethical Reasoning"
    domains = frozenset({"ethics", "policy", "general"})
    keywords = ("should we", "ethical", "fair", "privacy", "consent", "harm", "rights", "moral")
    base_score = 0.25

    async def apply(self, problem: str, context: ReasoningContext, *, models: Any | None = None) -> ReasoningResult:
        trace = _base_trace(problem, context)
        analysis = (
            "Ethical lens: stakeholders, harms/benefits, rights & consent, fairness, "
            "transparency, and reversibility."
        )
        conclusion = (
            f"Regarding «{problem}», prioritize minimizing harm and respecting consent/privacy, "
            "disclose trade-offs, and choose the path that remains defensible to affected parties."
        )
        return _finish(problem, self.kind, trace, analysis, conclusion, 0.58)


class CausalStrategy(_KeywordStrategy):
    kind = StrategyKind.CAUSAL
    name = "Causal Reasoning"
    domains = frozenset({"science", "diagnostics", "general"})
    keywords = ("why", "cause", "because", "lead to", "result in", "due to", "root cause")
    base_score = 0.3

    async def apply(self, problem: str, context: ReasoningContext, *, models: Any | None = None) -> ReasoningResult:
        trace = _base_trace(problem, context)
        analysis = "Causal chain: antecedents → mechanisms → effects; distinguish correlation from cause."
        conclusion = (
            f"Likely causes related to «{problem}» should be ordered by controllability and evidence. "
            "Intervene on the deepest cause you can influence; verify with a before/after check."
        )
        conf = 0.6 if (context.graph_facts or context.facts) else 0.48
        return _finish(problem, self.kind, trace, analysis, conclusion, conf)


class MultiStepStrategy(_KeywordStrategy):
    kind = StrategyKind.MULTI_STEP
    name = "Multi-Step Reasoning"
    domains = frozenset({"general"})
    keywords = ("step", "process", "then", "first", "finally")
    base_score = 0.15  # fallback-ish

    async def apply(self, problem: str, context: ReasoningContext, *, models: Any | None = None) -> ReasoningResult:
        trace = _base_trace(problem, context)
        analysis = "Multi-step decomposition: break into sub-goals, solve, recombine, verify."
        conclusion = (
            f"Approach «{problem}» in stages: (1) clarify success criteria, "
            "(2) inventory resources and constraints, (3) execute the highest-leverage next action, "
            "(4) review and adapt."
        )
        conf = 0.55 + (0.1 if context.memories else 0.0)
        return _finish(problem, self.kind, trace, analysis, conclusion, min(0.8, conf))


# Map legacy kinds
class DeductionStrategy(LogicalStrategy):
    kind = StrategyKind.DEDUCTION
    name = "Deductive Reasoning"


class InductionStrategy(_KeywordStrategy):
    kind = StrategyKind.INDUCTION
    name = "Inductive Reasoning"
    domains = frozenset({"general", "science"})
    keywords = ("pattern", "often", "usually", "trend", "typically", "in general")
    base_score = 0.3

    async def apply(self, problem: str, context: ReasoningContext, *, models: Any | None = None) -> ReasoningResult:
        trace = _base_trace(problem, context)
        analysis = "Inductive generalization from repeated observations; keep confidence modest."
        n = len(context.memories) + len(context.graph_facts)
        conclusion = (
            f"Patterns related to «{problem}» suggest a provisional rule"
            + (f" based on ~{n} observations" if n else "")
            + "; validate with more samples before high-stakes action."
        )
        conf = min(0.75, 0.4 + n * 0.05)
        return _finish(problem, self.kind, trace, analysis, conclusion, conf)


def register_builtin_strategies(registry: StrategyRegistry) -> None:
    for cls in (
        LogicalStrategy,
        DeductionStrategy,
        InductionStrategy,
        MathematicalStrategy,
        ScientificStrategy,
        BusinessStrategy,
        AgricultureStrategy,
        PlanningStrategy,
        RiskStrategy,
        DecisionStrategy,
        EthicalStrategy,
        CausalStrategy,
        MultiStepStrategy,
    ):
        registry.register(cls())

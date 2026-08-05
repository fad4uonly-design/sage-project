"""Explainable reasoning engine."""

from __future__ import annotations

from sage.logging import get_logger
from sage.models.interfaces import CompletionRequest, Message, ModelRouter
from sage.reasoning.models import (
    ReasoningContext,
    ReasoningResult,
    ReasoningStep,
    StrategyKind,
)

log = get_logger(__name__)


class DefaultReasoningEngine:
    """
    Structured multi-step reasoner.

    Always returns an explainable trace. Uses the model router when available,
    with a deterministic local fallback path so offline mode still works.
    """

    def __init__(self, models: ModelRouter | None = None) -> None:
        self._models = models

    async def reason(
        self,
        problem: str,
        *,
        context: ReasoningContext | None = None,
        strategy: StrategyKind = StrategyKind.AUTO,
    ) -> ReasoningResult:
        ctx = context or ReasoningContext()
        resolved = self._resolve_strategy(problem, strategy)
        trace: list[ReasoningStep] = []

        trace.append(
            ReasoningStep(
                index=0,
                thought=f"Understood problem: {problem}",
                kind="understand",
                confidence=0.9,
            )
        )

        if ctx.facts or ctx.memories or ctx.knowledge:
            evidence = [*ctx.facts[:5], *ctx.memories[:5], *ctx.knowledge[:5]]
            trace.append(
                ReasoningStep(
                    index=1,
                    thought="Gathered relevant context from memory and knowledge.",
                    kind="gather",
                    evidence=evidence,
                    confidence=0.7,
                )
            )
        else:
            trace.append(
                ReasoningStep(
                    index=1,
                    thought="No prior context supplied; reasoning from the problem statement alone.",
                    kind="gather",
                    confidence=0.4,
                )
            )

        if ctx.constraints:
            trace.append(
                ReasoningStep(
                    index=2,
                    thought="Applied constraints: " + "; ".join(ctx.constraints),
                    kind="constrain",
                    evidence=list(ctx.constraints),
                    confidence=0.8,
                )
            )

        analysis = self._local_analysis(problem, resolved, ctx)
        trace.append(
            ReasoningStep(
                index=len(trace),
                thought=analysis["analysis"],
                kind=resolved.value,
                confidence=analysis["confidence"],
            )
        )

        # Optional model enrichment
        model_conclusion = await self._model_assist(problem, resolved, ctx, trace)
        conclusion = model_conclusion or analysis["conclusion"]

        trace.append(
            ReasoningStep(
                index=len(trace),
                thought=f"Conclusion: {conclusion}",
                kind="conclude",
                confidence=analysis["confidence"],
            )
        )

        result = ReasoningResult(
            problem=problem,
            strategy=resolved,
            conclusion=conclusion,
            trace=trace,
            confidence=analysis["confidence"],
            alternatives=analysis.get("alternatives", []),
            risks=analysis.get("risks", []),
        )
        log.debug("reasoning.complete", strategy=resolved.value, steps=len(trace))
        return result

    def _resolve_strategy(self, problem: str, strategy: StrategyKind) -> StrategyKind:
        if strategy != StrategyKind.AUTO:
            return strategy
        lower = problem.lower()
        if any(w in lower for w in ("risk", "danger", "fail", "hazard")):
            return StrategyKind.RISK
        if any(w in lower for w in ("decide", "choose", "which", "option", "should i")):
            return StrategyKind.DECISION
        if any(w in lower for w in ("why", "cause", "because", "lead to")):
            return StrategyKind.CAUSAL
        if any(w in lower for w in ("pattern", "often", "usually", "trend")):
            return StrategyKind.INDUCTION
        if any(w in lower for w in ("if ", "therefore", "implies", "given that")):
            return StrategyKind.DEDUCTION
        if any(w in lower for w in ("step", "plan", "how to", "process")):
            return StrategyKind.MULTI_STEP
        return StrategyKind.MULTI_STEP

    def _local_analysis(
        self,
        problem: str,
        strategy: StrategyKind,
        ctx: ReasoningContext,
    ) -> dict:
        alternatives: list[str] = []
        risks: list[str] = []
        confidence = 0.55

        if strategy == StrategyKind.DECISION:
            alternatives = [
                "Option A: act immediately with current information",
                "Option B: gather more evidence before acting",
                "Option C: defer and monitor",
            ]
            analysis = (
                "Decision framing: clarify objective, list options, score by utility "
                "and risk, then pick the option with best expected outcome under constraints."
            )
            conclusion = (
                f"For «{problem}», prefer the option that maximizes expected value "
                "while respecting constraints"
                + (f" ({', '.join(ctx.constraints)})" if ctx.constraints else "")
                + ". Start with a reversible step to reduce downside."
            )
            risks = ["Incomplete information", "Irreversible commitment too early"]
        elif strategy == StrategyKind.RISK:
            analysis = "Risk analysis: identify hazards, likelihood, impact, and mitigations."
            conclusion = (
                f"Primary risks around «{problem}» should be mitigated with monitoring, "
                "fallback plans, and staged rollout."
            )
            risks = ["Execution failure", "Resource overrun", "External dependency failure"]
        elif strategy == StrategyKind.CAUSAL:
            analysis = "Causal chain: map antecedents → mechanisms → effects."
            conclusion = (
                f"Likely causes related to «{problem}» should be validated with "
                "intervening evidence before acting on the deepest controllable cause."
            )
        elif strategy == StrategyKind.DEDUCTION:
            analysis = "Deductive path: apply general rules to specific premises."
            conclusion = (
                f"From the stated premises about «{problem}», the logically entailed "
                "conclusion should be accepted only if all premises hold."
            )
            confidence = 0.6
        elif strategy == StrategyKind.INDUCTION:
            analysis = "Inductive path: generalize from repeated observations."
            conclusion = (
                f"Patterns related to «{problem}» suggest a provisional rule; "
                "keep confidence modest until more samples confirm it."
            )
            confidence = 0.45
        else:
            analysis = (
                "Multi-step decomposition: break the problem into sub-goals, "
                "solve each, then recombine."
            )
            conclusion = (
                f"Approach «{problem}» in stages: (1) clarify success criteria, "
                "(2) inventory resources and constraints, (3) execute the highest-leverage "
                "next action, (4) review and adapt."
            )

        if ctx.memories:
            confidence = min(0.85, confidence + 0.1)

        return {
            "analysis": analysis,
            "conclusion": conclusion,
            "confidence": confidence,
            "alternatives": alternatives,
            "risks": risks,
        }

    async def _model_assist(
        self,
        problem: str,
        strategy: StrategyKind,
        ctx: ReasoningContext,
        trace: list[ReasoningStep],
    ) -> str | None:
        if self._models is None:
            return None
        try:
            lm = self._models.get_language_model()
            system = (
                "You are the SAGE Reasoning Engine. Produce a concise, logical conclusion. "
                f"Strategy: {strategy.value}. Be explainable and practical."
            )
            ctx_blob = ""
            if ctx.memories:
                ctx_blob += "Memories:\n- " + "\n- ".join(ctx.memories[:8]) + "\n"
            if ctx.knowledge:
                ctx_blob += "Knowledge:\n- " + "\n- ".join(ctx.knowledge[:8]) + "\n"
            user = f"Problem: {problem}\n{ctx_blob}\nProvide the best conclusion in 2-4 sentences."
            resp = await lm.complete(
                CompletionRequest(
                    messages=[
                        Message(role="system", content=system),
                        Message(role="user", content=user),
                    ]
                )
            )
            # Prefer model text only if non-empty and not pure stub banner for generic cases
            text = (resp.content or "").strip()
            return text or None
        except Exception:
            log.exception("reasoning.model_assist_failed")
            return None

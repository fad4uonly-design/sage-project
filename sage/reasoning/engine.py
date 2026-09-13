"""
Strategy-based explainable reasoning engine.

Selects one or more specialized strategies, optionally fuses results,
and always emits an ExplainabilityReport.
"""

from __future__ import annotations

from typing import Any

from sage.logging import get_logger
from sage.models.interfaces import CompletionRequest, Message, ModelRouter
from sage.reasoning.models import (
    ExplainabilityReport,
    ReasoningContext,
    ReasoningResult,
    ReasoningStep,
    StrategyKind,
)
from sage.reasoning.strategies.base import StrategyRegistry
from sage.reasoning.strategies.builtin import register_builtin_strategies

log = get_logger(__name__)


class DefaultReasoningEngine:
    def __init__(
        self,
        models: ModelRouter | None = None,
        *,
        container: Any | None = None,
        registry: StrategyRegistry | None = None,
    ) -> None:
        self._models = models
        self._container = container
        self._registry = registry or StrategyRegistry()
        if registry is None:
            register_builtin_strategies(self._registry)

    @property
    def registry(self) -> StrategyRegistry:
        return self._registry

    async def reason(
        self,
        problem: str,
        *,
        context: ReasoningContext | None = None,
        strategy: StrategyKind = StrategyKind.AUTO,
        use_retrieval: bool = True,
        combine_top_k: int = 1,
    ) -> ReasoningResult:
        ctx = context or ReasoningContext()

        # Auto-enrich from retrieval if empty-ish
        if (
            use_retrieval
            and self._container is not None
            and not (ctx.memories or ctx.graph_facts or ctx.documents)
        ):
            ctx = await self._enrich_from_retrieval(problem, ctx)

        strategies = self._registry.select(
            problem,
            ctx,
            preferred=strategy if strategy != StrategyKind.AUTO else None,
            top_k=max(1, combine_top_k),
        )
        if not strategies:
            from sage.reasoning.strategies.builtin import MultiStepStrategy

            strategies = [MultiStepStrategy()]

        results: list[ReasoningResult] = []
        for strat in strategies:
            try:
                results.append(await strat.apply(problem, ctx, models=self._models))
            except Exception:
                log.exception("reasoning.strategy_failed", strategy=strat.kind.value)

        if not results:
            results = [
                ReasoningResult(
                    problem=problem,
                    strategy=StrategyKind.MULTI_STEP,
                    conclusion=f"Unable to complete reasoning for: {problem}",
                    confidence=0.2,
                    trace=[
                        ReasoningStep(index=0, thought="All strategies failed", kind="error", confidence=0.1)
                    ],
                )
            ]

        primary = results[0]
        if len(results) > 1:
            primary = self._fuse(results)

        # Optional model polish — skip stub/offline banners so strategy conclusions stay clean
        polished = await self._model_assist(problem, primary.strategy, ctx)
        if polished and self._is_usable_model_text(polished):
            primary.conclusion = polished
            primary.trace.append(
                ReasoningStep(
                    index=len(primary.trace),
                    thought="Model-assisted conclusion refinement applied.",
                    kind="model_refine",
                    confidence=primary.confidence,
                )
            )

        primary.explainability = self._build_explainability(problem, ctx, primary, results)
        primary.strategies_used = [r.strategy.value for r in results]
        log.debug(
            "reasoning.complete",
            strategy=primary.strategy.value,
            strategies=primary.strategies_used,
            confidence=primary.confidence,
            steps=len(primary.trace),
        )
        return primary

    async def _enrich_from_retrieval(
        self, problem: str, ctx: ReasoningContext
    ) -> ReasoningContext:
        from sage.retrieval.interfaces import Retriever

        retriever = self._container.try_resolve(Retriever) if self._container else None
        if not retriever:
            return ctx
        try:
            result = await retriever.retrieve(problem, limit=10)
        except Exception:
            log.exception("reasoning.retrieval_enrich_failed")
            return ctx
        return ctx.model_copy(
            update={
                "memories": list(ctx.memories) + list(result.memories),
                "graph_facts": list(ctx.graph_facts) + list(result.graph_facts),
                "documents": list(ctx.documents) + list(result.documents),
                "knowledge": list(ctx.knowledge)
                + [i.content for i in result.ranked if i.layer.value == "document"][:5],
                "metadata": {
                    **ctx.metadata,
                    "retrieval_confidence": result.overall_confidence,
                    "retrieval_explanation": result.explanation,
                },
            }
        )

    def _fuse(self, results: list[ReasoningResult]) -> ReasoningResult:
        """Combine multiple strategy outputs into one explainable result."""
        primary = results[0]
        # Confidence: weighted by individual confidence
        total = sum(r.confidence for r in results) or 1.0
        fused_conf = sum(r.confidence * r.confidence for r in results) / total
        # Merge alternatives/risks
        alts: list[str] = []
        risks: list[str] = []
        trace: list[ReasoningStep] = [
            ReasoningStep(
                index=0,
                thought=f"Fusing {len(results)} strategies: "
                + ", ".join(r.strategy.value for r in results),
                kind="fuse",
                confidence=fused_conf,
            )
        ]
        idx = 1
        conclusions: list[str] = []
        for r in results:
            conclusions.append(f"[{r.strategy.value}] {r.conclusion}")
            for step in r.trace:
                trace.append(
                    ReasoningStep(
                        index=idx,
                        thought=f"({r.strategy.value}) {step.thought}",
                        kind=step.kind,
                        evidence=step.evidence,
                        confidence=step.confidence,
                    )
                )
                idx += 1
            for a in r.alternatives:
                if a not in alts:
                    alts.append(a)
            for risk in r.risks:
                if risk not in risks:
                    risks.append(risk)

        fused_conclusion = (
            primary.conclusion
            + "\n\nAdditional perspectives:\n"
            + "\n".join(f"- {c}" for c in conclusions[1:])
        )
        return ReasoningResult(
            problem=primary.problem,
            strategy=primary.strategy,
            conclusion=fused_conclusion,
            trace=trace,
            confidence=min(0.92, fused_conf + 0.05),
            alternatives=alts,
            risks=risks,
            strategies_used=[r.strategy.value for r in results],
        )

    def _build_explainability(
        self,
        problem: str,
        ctx: ReasoningContext,
        primary: ReasoningResult,
        all_results: list[ReasoningResult],
    ) -> ExplainabilityReport:
        return ExplainabilityReport(
            question=problem,
            relevant_memories=list(ctx.memories)[:8],
            knowledge_graph_facts=list(ctx.graph_facts)[:8],
            supporting_documents=list(ctx.documents)[:5],
            reasoning_strategy=primary.strategy.value,
            strategies_used=[r.strategy.value for r in all_results],
            confidence_score=primary.confidence,
            final_answer=primary.conclusion,
            trace_summary=[f"({s.kind}) {s.thought}" for s in primary.trace],
            retrieval_explanation=list(ctx.metadata.get("retrieval_explanation") or []),
        )

    def _is_usable_model_text(self, text: str) -> bool:
        lower = text.lower()
        if not text.strip():
            return False
        if text.startswith("[SAGE stub"):
            return False
        if "stub model" in lower or "stub mode" in lower:
            return False
        if lower.startswith("reasoning (stub)"):
            return False
        return "connect a real model provider" not in lower

    async def _model_assist(
        self,
        problem: str,
        strategy: StrategyKind,
        ctx: ReasoningContext,
    ) -> str | None:
        if self._models is None:
            return None
        try:
            lm = self._models.get_language_model()
            if getattr(lm, "provider", "") == "stub":
                return None
            system = (
                "You are the SAGE Reasoning Engine. Produce a concise conclusion. "
                f"Strategy: {strategy.value}. Be explainable and practical. "
                "Output only the conclusion text, no preamble."
            )
            parts: list[str] = []
            if ctx.graph_facts:
                parts.append("Graph facts:\n- " + "\n- ".join(ctx.graph_facts[:8]))
            if ctx.memories:
                parts.append("Memories:\n- " + "\n- ".join(ctx.memories[:8]))
            if ctx.documents:
                parts.append("Documents:\n- " + "\n- ".join(ctx.documents[:4]))
            user = f"Problem: {problem}\n" + "\n".join(parts) + "\n\nConclusion in 2-4 sentences."
            resp = await lm.complete(
                CompletionRequest(
                    messages=[
                        Message(role="system", content=system),
                        Message(role="user", content=user),
                    ]
                )
            )
            return (resp.content or "").strip() or None
        except Exception:
            log.exception("reasoning.model_assist_failed")
            return None

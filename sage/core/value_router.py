"""ValueRouter: the four-question gate every request passes through before
anything expensive happens.

  1. Do we already know the answer?         -> MemoryInterface (real memory)
  2. How complex is this, really?           -> WasteDetector.classify_complexity
  3. What's the cheapest sufficient model?  -> ModelRegistry.cheapest_sufficient
  4. Does this need tools at all?           -> WasteDetector.needs_tool

The router itself must be cheap: it uses heuristics and memory lookups,
never a full model call, to decide whether a full model call is warranted.
It sits IN FRONT of the existing reasoning/planning stack as a gate, not a
replacement.

Note on async: ``route()`` is async because SAGE's real memory system
(``SQLiteMemorySystem`` / ``SqliteVectorIndex``) is async. The heuristic
work here is still O(request length) — the router never spawns a model call.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from sage.core.waste_detector import Complexity, WasteDetector, WasteReport
from sage.memory.memory_interface import MemoryHit, MemoryInterface
from sage.models.model_card import ModelCard
from sage.models.registry import ModelRegistry

#: Cosine confidence at which a memory hit answers the request outright.
#: Calibrated for real embedding spaces; lower it (e.g. 0.85) when running
#: on the offline HashingEmbeddingModel, whose exact repeats land ~0.87.
MEMORY_ONLY_CONFIDENCE = 0.90


class RoutingDecision(Enum):
    MEMORY_ONLY = "memory_only"      # answer straight from memory, no model call
    CHEAP_MODEL = "cheap_model"      # trivial/moderate, small model sufficient
    FULL_PIPELINE = "full_pipeline"  # complex, needs strong reasoning +/- tools


@dataclass
class RoutePlan:
    decision: RoutingDecision
    model: ModelCard | None
    use_tools: bool
    memory_hit: MemoryHit | None
    waste_report: WasteReport
    rationale: str


class ValueRouter:
    """Decides how much work a request deserves before any model is called.

    Args:
        registry: model catalog consulted for the cheapest sufficient tier.
        memory: optional ``MemoryInterface`` wired to the real memory
            system. When ``None`` the router skips memory lookups entirely
            (pure complexity/tool routing) instead of constructing a fake
            store.
        waste_detector: session-scoped waste heuristics.
        memory_only_confidence: hit confidence required to short-circuit
            execution entirely (the "pull" principle).
    """

    def __init__(
        self,
        registry: ModelRegistry | None = None,
        memory: MemoryInterface | None = None,
        waste_detector: WasteDetector | None = None,
        *,
        memory_only_confidence: float = MEMORY_ONLY_CONFIDENCE,
    ) -> None:
        self.registry = registry or ModelRegistry()
        self.memory = memory
        self.waste = waste_detector or WasteDetector()
        self.memory_only_confidence = memory_only_confidence

    async def route(self, request_text: str) -> RoutePlan:
        memory_hit = (
            await self.memory.lookup(request_text) if self.memory is not None else None
        )
        waste_report = self.waste.evaluate(request_text, memory_hit=memory_hit is not None)

        # 1. Pull principle: if memory already answers this, do nothing else.
        if memory_hit is not None and memory_hit.confidence >= self.memory_only_confidence:
            return RoutePlan(
                decision=RoutingDecision.MEMORY_ONLY,
                model=None,
                use_tools=False,
                memory_hit=memory_hit,
                waste_report=waste_report,
                rationale=(
                    f"Answer already in memory (confidence {memory_hit.confidence:.2f} "
                    f">= {self.memory_only_confidence:.2f}) — skip model call entirely."
                ),
            )

        needs_tools = waste_report.needs_tool
        needs_reasoning = waste_report.complexity == Complexity.COMPLEX
        needs_long_context = 100_000 if needs_reasoning else 0

        model = self.registry.cheapest_sufficient(
            needs_reasoning=needs_reasoning,
            needs_tools=needs_tools,
            needs_long_context_tokens=needs_long_context,
        )

        if waste_report.complexity == Complexity.TRIVIAL and not needs_tools:
            decision = RoutingDecision.CHEAP_MODEL
            rationale = "Trivial request, no tools needed — route to cheapest sufficient model."
        elif waste_report.complexity == Complexity.COMPLEX or needs_tools:
            decision = RoutingDecision.FULL_PIPELINE
            rationale = (
                "Complex reasoning and/or tool use required — route to strongest sufficient model."
            )
        else:
            decision = RoutingDecision.CHEAP_MODEL
            rationale = (
                "Moderate complexity, no escalation triggers — default to cheapest sufficient model."
            )

        return RoutePlan(
            decision=decision,
            model=model,
            use_tools=needs_tools,
            memory_hit=memory_hit,
            waste_report=waste_report,
            rationale=rationale,
        )

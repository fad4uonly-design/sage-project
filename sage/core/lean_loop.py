"""LeanLoop: orchestrates the full cycle from request to Kaizen update.

    REQUEST -> VALUE ANALYSIS -> PLAN MINIMUM WORK -> EXECUTE
            -> VERIFY -> DELIVER -> MEASURE -> KAIZEN -> UPDATE MEMORY

This class does not implement reasoning/tool execution itself — it calls out
to an ``executor`` callable, which is where SAGE's existing reasoning/
planning/agent modules plug in. That's the intended seam: LeanLoop governs
*whether and how* execution happens; it doesn't reimplement execution.

Note on async: ``run()`` is async because SAGE's real memory system and the
executor seam are async (``SQLiteMemorySystem``, event bus, model adapters).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sage.core.value_router import RoutePlan, RoutingDecision, ValueRouter
from sage.models.model_card import ModelCard

#: Signature the caller must provide:
#:   async executor(request_text, model: ModelCard | None, use_tools: bool) -> str
ExecutorFn = Callable[[str, "ModelCard | None", bool], Awaitable[str]]
#: Optional quality-at-source check: verifier(request, result) -> bool.
VerifierFn = Callable[[str, str], bool]

#: Rough token assumption for the placeholder cost estimate (in + out).
_ASSUMED_TOKENS = 500


@dataclass
class TaskOutcome:
    request_text: str
    decision: RoutingDecision
    model_used: str | None
    used_tools: bool
    result: str
    latency_seconds: float
    estimated_cost_usd: float
    verified: bool
    notes: list[str] = field(default_factory=list)


class LeanLoop:
    """Governed execution loop with Kaizen bookkeeping.

    Args:
        router: the value gate in front of execution.
        verifier: quality-at-source check run before delivery; a falsy
            return stops the line (Jidoka) and marks the request as failed
            so rework is flagged on the next attempt. Defaults to
            "non-empty result".
    """

    def __init__(
        self,
        router: ValueRouter | None = None,
        verifier: VerifierFn | None = None,
    ) -> None:
        self.router = router or ValueRouter()
        self.verifier: VerifierFn = verifier or (
            lambda request, result: bool(result and result.strip())
        )
        self.log: list[TaskOutcome] = []

    async def run(self, request_text: str, executor: ExecutorFn) -> TaskOutcome:
        start = time.perf_counter()

        # 1. VALUE ANALYSIS + PLAN MINIMUM WORK
        plan: RoutePlan = await self.router.route(request_text)

        # 2. EXECUTE (short-circuit for memory-only)
        if plan.decision == RoutingDecision.MEMORY_ONLY and plan.memory_hit is not None:
            result = plan.memory_hit.value
        else:
            result = await executor(request_text, plan.model, plan.use_tools)

        # 3. VERIFY (quality at source)
        verified = self.verifier(request_text, result)
        if not verified:
            # Jidoka: stop and flag rather than silently deliver a bad result.
            self.router.waste.record_failure(request_text)

        # 4. MEASURE
        outcome = TaskOutcome(
            request_text=request_text,
            decision=plan.decision,
            model_used=plan.model.identity.name if plan.model else None,
            used_tools=plan.use_tools,
            result=result,
            latency_seconds=time.perf_counter() - start,
            estimated_cost_usd=self._estimate_cost(plan),
            verified=verified,
            notes=[*plan.waste_report.notes, plan.rationale],
        )

        # 5. KAIZEN: write durable results back to real memory, keep the log.
        if (
            verified
            and plan.decision != RoutingDecision.MEMORY_ONLY
            and self.router.memory is not None
        ):
            await self.router.memory.write(request_text, result)
        self.record_outcome(outcome)

        return outcome

    def record_outcome(self, outcome: TaskOutcome) -> None:
        """Kaizen hook: every outcome lands in the log. This log is the raw
        material for continuous improvement / dashboard surfacing."""
        self.log.append(outcome)

    @staticmethod
    def _estimate_cost(plan: RoutePlan) -> float:
        if plan.decision == RoutingDecision.MEMORY_ONLY or plan.model is None:
            return 0.0
        # Extremely rough placeholder: assume ~500 tokens in, ~500 out.
        # Replace with real token counts once wired to actual model calls.
        model = plan.model
        if model.identity.provider == "local":
            return 0.0
        in_cost = (model.cost.input_per_million_tokens_usd or 0) * _ASSUMED_TOKENS / 1_000_000
        out_cost = (model.cost.output_per_million_tokens_usd or 0) * _ASSUMED_TOKENS / 1_000_000
        return round(in_cost + out_cost, 6)

    def waste_summary(self) -> dict[str, float | int]:
        """Aggregate stats for the Kaizen review / dashboard."""
        total = len(self.log)
        if total == 0:
            return {"total_tasks": 0}
        memory_only = sum(1 for o in self.log if o.decision == RoutingDecision.MEMORY_ONLY)
        cheap = sum(1 for o in self.log if o.decision == RoutingDecision.CHEAP_MODEL)
        full = sum(1 for o in self.log if o.decision == RoutingDecision.FULL_PIPELINE)
        failed = sum(1 for o in self.log if not o.verified)
        total_cost = sum(o.estimated_cost_usd for o in self.log)
        return {
            "total_tasks": total,
            "answered_from_memory_pct": round(100 * memory_only / total, 1),
            "routed_cheap_pct": round(100 * cheap / total, 1),
            "routed_full_pipeline_pct": round(100 * full / total, 1),
            "verification_failures": failed,
            "estimated_total_cost_usd": round(total_cost, 4),
        }

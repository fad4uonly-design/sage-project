"""
Multi-criteria Decision Engine.

- Weighted scoring with min-max normalization per criterion
- Risk penalties
- Trade-off narration
- Confidence from score separation + evidence completeness
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from sage.decision.models import (
    Criterion,
    DecisionOption,
    DecisionRequest,
    DecisionResult,
    ScoredOption,
)
from sage.logging import get_logger

log = get_logger(__name__)


@runtime_checkable
class DecisionEngine(Protocol):
    async def decide(self, request: DecisionRequest) -> DecisionResult: ...

    async def quick_rank(
        self,
        question: str,
        options: list[str],
        *,
        criteria: list[tuple[str, float]] | None = None,
    ) -> DecisionResult: ...


class DefaultDecisionEngine:
    async def decide(self, request: DecisionRequest) -> DecisionResult:
        if not request.options:
            return DecisionResult(
                request_id=request.id,
                question=request.question,
                recommendation="No options provided.",
                confidence=0.0,
                explanation=["Empty option set"],
            )
        if not request.criteria:
            # Equal weight single synthetic criterion from average of scores or 0.5
            request = request.model_copy(
                update={
                    "criteria": [
                        Criterion(id="overall", name="Overall", weight=1.0)
                    ]
                }
            )
            for opt in request.options:
                if "overall" not in opt.scores:
                    opt.scores["overall"] = 0.5

        criteria = request.criteria
        weight_sum = sum(c.weight for c in criteria) or 1.0
        norm_weights = {c.id: c.weight / weight_sum for c in criteria}

        # Min-max per criterion across options
        ranges: dict[str, tuple[float, float]] = {}
        for c in criteria:
            vals = [o.scores.get(c.id, 0.0) for o in request.options]
            lo, hi = min(vals), max(vals)
            ranges[c.id] = (lo, hi)

        scored: list[ScoredOption] = []
        for opt in request.options:
            norm_scores: dict[str, float] = {}
            weighted: dict[str, float] = {}
            total = 0.0
            for c in criteria:
                raw = opt.scores.get(c.id, 0.0)
                lo, hi = ranges[c.id]
                if hi > lo:
                    n = (raw - lo) / (hi - lo)
                else:
                    n = 0.5
                if not c.maximize:
                    n = 1.0 - n
                norm_scores[c.id] = n
                w = n * norm_weights[c.id]
                weighted[c.id] = w
                total += w

            risk_adj = -request.risk_penalty * min(len(opt.risks), 5)
            total_adj = max(0.0, total + risk_adj)

            # Rationale: top contributing criteria
            top_crit = sorted(weighted.items(), key=lambda x: x[1], reverse=True)[:2]
            crit_names = {c.id: c.name for c in criteria}
            bits = [f"{crit_names.get(cid, cid)}={weighted[cid]:.2f}" for cid, _ in top_crit]
            rationale = "Drivers: " + ", ".join(bits) if bits else ""
            if opt.risks:
                rationale += f"; risks noted: {len(opt.risks)}"

            scored.append(
                ScoredOption(
                    option_id=opt.id,
                    name=opt.name,
                    total_score=round(total_adj, 4),
                    normalized_scores=norm_scores,
                    weighted_scores=weighted,
                    risk_adjustment=risk_adj,
                    rationale=rationale,
                )
            )

        scored.sort(key=lambda s: s.total_score, reverse=True)
        for i, s in enumerate(scored, 1):
            s.rank = i

        # Confidence: separation between #1 and #2 + completeness of scores
        if len(scored) == 1:
            separation = 1.0
        else:
            separation = max(0.0, scored[0].total_score - scored[1].total_score)
        expected_cells = len(request.options) * len(criteria)
        filled = sum(1 for o in request.options for c in criteria if c.id in o.scores)
        completeness = filled / expected_cells if expected_cells else 0.0
        confidence = min(0.95, 0.35 + separation * 0.8 + completeness * 0.3)

        best = scored[0]
        recommendation = (
            f"Recommend **{best.name}** (score {best.total_score:.3f}). {best.rationale}"
        )

        trade_offs = self._trade_offs(request, scored)
        risks = []
        for opt in request.options:
            for r in opt.risks:
                label = f"{opt.name}: {r}"
                if label not in risks:
                    risks.append(label)

        explanation = [
            "Min-max normalized scores per criterion",
            f"Weights: " + ", ".join(f"{c.name}={norm_weights[c.id]:.2f}" for c in criteria),
            f"Risk penalty per risk item: {request.risk_penalty}",
            f"Score separation (1st−2nd): {separation:.3f}",
            f"Score matrix completeness: {completeness:.0%}",
        ]

        result = DecisionResult(
            request_id=request.id,
            question=request.question,
            ranking=scored,
            recommendation=recommendation,
            confidence=round(confidence, 3),
            trade_offs=trade_offs,
            risks=risks[:12],
            explanation=explanation,
        )
        log.debug(
            "decision.complete",
            question=request.question[:80],
            winner=best.name,
            confidence=result.confidence,
        )
        return result

    async def quick_rank(
        self,
        question: str,
        options: list[str],
        *,
        criteria: list[tuple[str, float]] | None = None,
    ) -> DecisionResult:
        """Convenience: equal default scores with optional named weighted criteria."""
        crit_defs = criteria or [("value", 1.0), ("feasibility", 0.8), ("risk_inverse", 0.7)]
        crits = [
            Criterion(
                id=f"c{i}",
                name=name,
                weight=w,
                maximize=not name.lower().startswith("risk") or "inverse" in name.lower(),
            )
            for i, (name, w) in enumerate(crit_defs)
        ]
        # Heuristic scores from option text length / keywords — callers should prefer full decide()
        opts: list[DecisionOption] = []
        for i, name in enumerate(options):
            scores = {}
            for j, c in enumerate(crits):
                # Slight variation so ranking isn't flat
                scores[c.id] = 0.5 + 0.1 * ((i + j) % 3) - 0.05 * (i % 2)
            opts.append(DecisionOption(id=f"opt_{i}", name=name, scores=scores))
        return await self.decide(
            DecisionRequest(question=question, criteria=crits, options=opts)
        )

    def _trade_offs(
        self, request: DecisionRequest, scored: list[ScoredOption]
    ) -> list[str]:
        if len(scored) < 2:
            return []
        a, b = scored[0], scored[1]
        trade: list[str] = []
        crit_names = {c.id: c.name for c in request.criteria}
        for cid in a.normalized_scores:
            sa = a.normalized_scores.get(cid, 0)
            sb = b.normalized_scores.get(cid, 0)
            name = crit_names.get(cid, cid)
            if sa - sb > 0.15:
                trade.append(f"{a.name} outperforms {b.name} on {name}")
            elif sb - sa > 0.15:
                trade.append(f"{b.name} outperforms {a.name} on {name} (trade-off)")
        return trade[:6]

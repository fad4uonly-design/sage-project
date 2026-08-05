"""Shared decision skills — wrap Decision Engine for reuse."""

from __future__ import annotations

from typing import Any

from sage.skills.base import BaseSkill
from sage.skills.models import SkillCategory, SkillManifest, SkillRequest, SkillResult


class WeightedComparisonSkill(BaseSkill):
    manifest = SkillManifest(
        id="skill_decision_weighted",
        name="Weighted Comparison",
        category=SkillCategory.DECISION,
        description="Multi-criteria weighted comparison via Decision Engine",
        tags=["compare", "weighted", "multi-criteria", "mcda", "rank options", "vs"],
        examples=["compare option A vs B vs C for equipment purchase"],
    )

    async def run(self, request: SkillRequest) -> SkillResult:
        task = self._task(request)
        decide_fn = request.context.get("_decide_fn")
        # Build default options from params or generics
        from sage.decision.models import Criterion, DecisionOption, DecisionRequest

        raw_options = request.params.get("options") or ["Option A", "Option B", "Option C"]
        if isinstance(raw_options, str):
            raw_options = [o.strip() for o in raw_options.split(",") if o.strip()]
        opts = []
        for i, name in enumerate(raw_options[:6]):
            opts.append(
                DecisionOption(
                    id=f"opt_{i}",
                    name=str(name),
                    scores={
                        "value": 0.5 + 0.1 * ((i + 1) % 3),
                        "feasibility": 0.6 - 0.05 * (i % 2),
                        "risk": 0.3 + 0.1 * (i % 3),
                    },
                    risks=["Execution uncertainty"] if i else [],
                )
            )
        req = DecisionRequest(
            question=task or "Which option is best?",
            criteria=[
                Criterion(id="value", name="Value", weight=0.4),
                Criterion(id="feasibility", name="Feasibility", weight=0.35),
                Criterion(id="risk", name="Risk", weight=0.25, maximize=False),
            ],
            options=opts,
        )
        decision = None
        if callable(decide_fn):
            try:
                decision = await decide_fn(req)
            except Exception:
                decision = None
        if decision is None:
            # Local fallback engine
            from sage.decision.engine import DefaultDecisionEngine

            decision = await DefaultDecisionEngine().decide(req)

        output = decision.format() if decision else "Decision unavailable."
        conf = float(getattr(decision, "confidence", 0.6) or 0.6)
        return self._ok(
            output,
            steps=[
                {"id": "s1", "title": "Frame criteria", "status": "done"},
                {"id": "s2", "title": "Score options", "status": "done"},
                {"id": "s3", "title": "Rank & explain", "status": "done"},
            ],
            data={"decision_id": getattr(decision, "request_id", None)},
            confidence=conf,
            request=request,
        )


class TradeoffAnalysisSkill(BaseSkill):
    manifest = SkillManifest(
        id="skill_decision_tradeoff",
        name="Trade-off Analysis",
        category=SkillCategory.DECISION,
        description="Explicit trade-off narrative between competing goals",
        tags=["trade-off", "tradeoff", "trade offs", "pros and cons", "tension"],
        examples=["trade-off analysis growth vs margin"],
    )

    async def run(self, request: SkillRequest) -> SkillResult:
        task = self._task(request)
        lines = [
            f"**Trade-off Analysis** — {task[:140]}",
            "",
            "| Dimension | Lean A | Lean B |",
            "|---|---|---|",
            "| Speed | Faster learning | Higher rework risk |",
            "| Quality | Fewer defects | Slower delivery |",
            "| Cost | Lower near-term spend | Possible long-term cost |",
            "| Scope | Focus / depth | Breadth / optionality |",
            "",
            "**Method:** name the two poles, score must-haves, pick reversible steps first.",
            "**Recommendation:** optimize the constrained resource; time-box the other pole.",
        ]
        return self._ok(
            "\n".join(lines),
            steps=[
                {"id": "s1", "title": "Poles", "status": "done"},
                {"id": "s2", "title": "Table", "status": "done"},
                {"id": "s3", "title": "Recommend", "status": "done"},
            ],
            confidence=0.65,
            request=request,
        )


class RecommendationSkill(BaseSkill):
    manifest = SkillManifest(
        id="skill_decision_recommend",
        name="Recommendations",
        category=SkillCategory.DECISION,
        description="Prioritized recommendation block with confidence",
        tags=["recommend", "recommendation", "what should we do", "advise"],
        examples=["recommend next steps for market entry"],
    )

    async def run(self, request: SkillRequest) -> SkillResult:
        task = self._task(request)
        mem = self._ctx_list(request, "memories")
        graph = self._ctx_list(request, "graph_facts")
        lines = [
            f"**Recommendation** — {task[:140]}",
            "",
            "1. **Primary:** Run a time-boxed pilot with explicit success metrics.",
            "2. **Supporting:** Instrument leading indicators weekly.",
            "3. **Guardrail:** Cap irreversible spend until gates pass.",
            "",
            f"**Confidence:** {'moderate-high' if (mem or graph) else 'moderate'} "
            f"based on {len(mem)} memories and {len(graph)} graph facts.",
        ]
        if mem:
            lines.append(f"- Evidence (memory): {mem[0][:140]}")
        if graph:
            lines.append(f"- Evidence (graph): {graph[0][:140]}")
        return self._ok(
            "\n".join(lines),
            steps=[
                {"id": "s1", "title": "Synthesize", "status": "done"},
                {"id": "s2", "title": "Prioritize", "status": "done"},
            ],
            evidence=(mem + graph)[:6],
            confidence=0.7 if (mem or graph) else 0.58,
            request=request,
        )

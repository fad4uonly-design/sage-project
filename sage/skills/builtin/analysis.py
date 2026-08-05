"""Shared analysis skills."""

from __future__ import annotations

from sage.skills.base import BaseSkill
from sage.skills.models import SkillCategory, SkillManifest, SkillRequest, SkillResult


class SWOTSkill(BaseSkill):
    manifest = SkillManifest(
        id="skill_analysis_swot",
        name="SWOT Analysis",
        category=SkillCategory.ANALYSIS,
        description="Strengths, Weaknesses, Opportunities, Threats framework",
        tags=["swot", "strengths", "weaknesses", "opportunities", "threats", "analysis"],
        domains=[],  # universal
        examples=["SWOT for organic farm expansion", "strengths and weaknesses of our product"],
    )

    async def run(self, request: SkillRequest) -> SkillResult:
        task = self._task(request)
        farm = any(w in task.lower() for w in ("farm", "crop", "agriculture", "produce"))
        s = ["Core capability", "Customer proximity", "Execution speed"]
        w = ["Limited capital", "Process maturity", "Brand reach"]
        o = ["Adjacent segments", "Partnerships", "Digital channels"]
        t = ["Competition", "Cost inflation", "Regulation"]
        if farm:
            s.append("Production / land base")
            o.append("Premium / direct-to-consumer")
            t.append("Weather & disease pressure")
        graph = self._ctx_list(request, "graph_facts")
        mem = self._ctx_list(request, "memories")
        lines = [
            f"**SWOT** — {task[:140] or 'subject'}",
            "",
            "**Strengths**",
            *[f"- {x}" for x in s],
            "",
            "**Weaknesses**",
            *[f"- {x}" for x in w],
            "",
            "**Opportunities**",
            *[f"- {x}" for x in o],
            "",
            "**Threats**",
            *[f"- {x}" for x in t],
            "",
            "**Strategic moves:** SO bets first; pair each threat with a mitigation; "
            "time-box one weakness improvement.",
        ]
        evidence = mem[:3] + graph[:4]
        return self._ok(
            "\n".join(lines),
            steps=[
                {"id": "s1", "title": "Context", "status": "done"},
                {"id": "s2", "title": "Four quadrants", "status": "done"},
                {"id": "s3", "title": "Moves", "status": "done"},
            ],
            data={"framework": "swot", "farm_context": farm},
            evidence=evidence,
            confidence=0.72 if evidence else 0.6,
            request=request,
        )


class RiskAssessmentSkill(BaseSkill):
    manifest = SkillManifest(
        id="skill_analysis_risk",
        name="Risk Assessment",
        category=SkillCategory.ANALYSIS,
        description="Likelihood × impact risk matrix with mitigations",
        tags=["risk", "assessment", "threat", "mitigation", "hazard", "matrix"],
        examples=["risk assessment for expansion", "assess project risks"],
    )

    async def run(self, request: SkillRequest) -> SkillResult:
        task = self._task(request)
        lines = [
            f"**Risk Assessment** — {task[:140]}",
            "",
            "| Category | Example | L | I | Score | Response |",
            "|---|---|---:|---:|---:|---|",
            "| Strategic | Wrong market | 2 | 5 | 10 | Validate faster |",
            "| Financial | Cash shortfall | 3 | 5 | 15 | Buffer + forecast |",
            "| Operational | Key process fail | 3 | 4 | 12 | Redundancy |",
            "| Compliance | Regulatory miss | 2 | 5 | 10 | Checklist + counsel |",
            "| External | Supply shock | 3 | 3 | 9 | Dual-source |",
            "",
            "Own every score ≥ 12; review weekly.",
        ]
        return self._ok(
            "\n".join(lines),
            steps=[
                {"id": "s1", "title": "Identify", "status": "done"},
                {"id": "s2", "title": "Score", "status": "done"},
                {"id": "s3", "title": "Respond", "status": "done"},
            ],
            evidence=self._ctx_list(request, "graph_facts")[:4],
            confidence=0.68,
            request=request,
        )


class KPIAnalysisSkill(BaseSkill):
    manifest = SkillManifest(
        id="skill_analysis_kpi",
        name="KPI Analysis",
        category=SkillCategory.ANALYSIS,
        description="KPI tree, cadence, and bottleneck lens",
        tags=["kpi", "metrics", "dashboard", "performance", "okrs", "indicators"],
        examples=["KPI analysis for subscription business", "define metrics for farm ops"],
    )

    async def run(self, request: SkillRequest) -> SkillResult:
        task = self._task(request)
        lines = [
            f"**KPI Analysis** — {task[:140]}",
            "",
            "| Layer | Examples | Cadence |",
            "|---|---|---|",
            "| North star | Active paying / margin $ / yield quality | Weekly |",
            "| Growth | Leads, conversion, CAC | Weekly |",
            "| Delivery | On-time %, defect %, cycle time | Daily/weekly |",
            "| Finance | Cash, burn, runway, contribution | Weekly |",
            "",
            "**Method:** pick north star → 3–5 input metrics → owner + target → review ritual.",
            "Max 7–9 visible KPIs; deep-dives on demand.",
        ]
        return self._ok(
            "\n".join(lines),
            steps=[
                {"id": "s1", "title": "North star", "status": "done"},
                {"id": "s2", "title": "Input metrics", "status": "done"},
                {"id": "s3", "title": "Cadence", "status": "done"},
            ],
            evidence=self._ctx_list(request, "memories")[:3],
            confidence=0.7,
            request=request,
        )

"""Shared reporting skills."""

from __future__ import annotations

from sage.skills.base import BaseSkill
from sage.skills.models import SkillCategory, SkillManifest, SkillRequest, SkillResult


class ReportOutlineSkill(BaseSkill):
    manifest = SkillManifest(
        id="skill_reporting_outline",
        name="Report Outline",
        category=SkillCategory.REPORTING,
        description="Structured report outline (PDF/doc ready skeleton)",
        tags=["report", "pdf report", "write a report", "report outline", "documentation"],
        examples=["report outline for Q3 farm performance"],
    )

    async def run(self, request: SkillRequest) -> SkillResult:
        task = self._task(request)
        lines = [
            f"**Report Outline** — {task[:140]}",
            "",
            "1. Title page & period",
            "2. Executive summary (½ page)",
            "3. Objectives & scope",
            "4. Methods / data sources",
            "5. Findings (charts + narrative)",
            "6. Analysis & implications",
            "7. Recommendations (prioritized)",
            "8. Risks & open questions",
            "9. Appendix (tables, sources)",
            "",
            "_Export path (v0.4+): render outline → markdown/PDF via reporting tool._",
        ]
        return self._ok(
            "\n".join(lines),
            steps=[
                {"id": "s1", "title": "Structure", "status": "done"},
                {"id": "s2", "title": "Sections", "status": "done"},
            ],
            confidence=0.7,
            request=request,
        )


class DashboardOutlineSkill(BaseSkill):
    manifest = SkillManifest(
        id="skill_reporting_dashboard",
        name="Dashboard Outline",
        category=SkillCategory.REPORTING,
        description="Dashboard layout and metric placement",
        tags=["dashboard", "kpi dashboard", "metrics board", "scorecard"],
        examples=["dashboard for sales and ops"],
    )

    async def run(self, request: SkillRequest) -> SkillResult:
        task = self._task(request)
        lines = [
            f"**Dashboard Outline** — {task[:140]}",
            "",
            "| Zone | Content |",
            "|---|---|",
            "| Header | Period, filters, last refresh |",
            "| North star | 1 big number + sparkline |",
            "| Growth row | 3–4 acquisition/retention tiles |",
            "| Ops row | Quality / throughput / incidents |",
            "| Finance row | Cash, margin, burn |",
            "| Detail | Table + drill-down |",
            "",
            "Rule: scannable in 10 seconds; every tile has owner + target.",
        ]
        return self._ok(
            "\n".join(lines),
            steps=[
                {"id": "s1", "title": "Zones", "status": "done"},
                {"id": "s2", "title": "Tiles", "status": "done"},
            ],
            confidence=0.68,
            request=request,
        )


class ExecutiveSummarySkill(BaseSkill):
    manifest = SkillManifest(
        id="skill_reporting_exec_summary",
        name="Executive Summary",
        category=SkillCategory.REPORTING,
        description="Short executive summary from context",
        tags=["executive summary", "exec summary", "summary for leadership", "brief summary"],
        examples=["executive summary of irrigation expansion decision"],
    )

    async def run(self, request: SkillRequest) -> SkillResult:
        task = self._task(request)
        mem = self._ctx_list(request, "memories")
        graph = self._ctx_list(request, "graph_facts")
        lines = [
            "**Executive Summary**",
            "",
            f"**Topic:** {task[:160] or 'Current initiative'}",
            "",
            "**Situation:** Key facts assembled from memory and knowledge graph.",
        ]
        if mem:
            lines.append(f"- Memory: {mem[0][:160]}")
        if graph:
            lines.append(f"- Graph: {graph[0][:160]}")
        if not mem and not graph:
            lines.append("- Limited prior evidence; recommend gathering baselines.")
        lines += [
            "",
            "**Recommendation:** Proceed with a time-boxed pilot, clear success metrics, "
            "and weekly review. Defer irreversible spend until pilot gates pass.",
            "",
            "**Ask of leadership:** Approve pilot scope, owner, and budget ceiling.",
        ]
        return self._ok(
            "\n".join(lines),
            steps=[
                {"id": "s1", "title": "Synthesize", "status": "done"},
                {"id": "s2", "title": "Recommend", "status": "done"},
                {"id": "s3", "title": "Ask", "status": "done"},
            ],
            evidence=(mem + graph)[:6],
            confidence=0.66 if (mem or graph) else 0.55,
            request=request,
        )

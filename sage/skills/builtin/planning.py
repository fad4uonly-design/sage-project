"""Shared planning skills."""

from __future__ import annotations

from sage.skills.base import BaseSkill
from sage.skills.models import SkillCategory, SkillManifest, SkillRequest, SkillResult


class ProjectPlanningSkill(BaseSkill):
    manifest = SkillManifest(
        id="skill_planning_project",
        name="Project Planning",
        category=SkillCategory.PLANNING,
        description="Goal decomposition into milestones and controls",
        tags=["project plan", "project planning", "wbs", "milestone", "roadmap", "schedule"],
        examples=["project plan for warehouse rollout"],
    )

    async def run(self, request: SkillRequest) -> SkillResult:
        task = self._task(request)
        # Prefer real planning engine when container-like context provides it
        plan_text = ""
        planner = request.context.get("_plan_fn")
        if callable(planner):
            try:
                plan_text = await planner(task)
            except Exception:
                plan_text = ""
        lines = [
            f"**Project Planning** — {task[:140]}",
            "",
            plan_text
            or (
                "1. Clarify done / success criteria\n"
                "2. Work breakdown (epics → tasks)\n"
                "3. Dependencies & critical path\n"
                "4. Resources & calendar\n"
                "5. Risks (RAID) + weekly controls"
            ),
            "",
            "**Controls:** RACI, change board, status template (status / blockers / ask).",
        ]
        return self._ok(
            "\n".join(lines),
            steps=[
                {"id": "s1", "title": "Scope", "status": "done"},
                {"id": "s2", "title": "WBS", "status": "done"},
                {"id": "s3", "title": "Controls", "status": "done"},
            ],
            confidence=0.75 if plan_text else 0.62,
            request=request,
        )


class BudgetPlanningSkill(BaseSkill):
    manifest = SkillManifest(
        id="skill_planning_budget",
        name="Budget Planning",
        category=SkillCategory.PLANNING,
        description="Simple budget allocation framework",
        tags=["budget", "budgeting", "allocate", "spending plan", "financial plan"],
        examples=["budget plan for 10000 monthly revenue"],
    )

    async def run(self, request: SkillRequest) -> SkillResult:
        task = self._task(request)
        income = self._num(task, 10000.0)
        lines = [
            f"**Budget Planning** (reference inflow {income:,.2f})",
            "",
            f"- Direct / COGS (35%): {income * 0.35:,.2f}",
            f"- Operating expenses (40%): {income * 0.40:,.2f}",
            f"- Growth investment (15%): {income * 0.15:,.2f}",
            f"- Reserve / profit (10%): {income * 0.10:,.2f}",
            "",
            "Assign owners; variance review monthly; protect contingency.",
        ]
        return self._ok(
            "\n".join(lines),
            steps=[
                {"id": "s1", "title": "Inflow", "status": "done"},
                {"id": "s2", "title": "Allocate", "status": "done"},
                {"id": "s3", "title": "Owners", "status": "done"},
            ],
            data={"income": income},
            confidence=0.7,
            request=request,
        )


class CropPlanningSkill(BaseSkill):
    manifest = SkillManifest(
        id="skill_planning_crop",
        name="Crop Planning",
        category=SkillCategory.PLANNING,
        description="Seasonal crop calendar and stage plan",
        tags=["crop plan", "crop planning", "planting", "harvest calendar", "grow plan"],
        domains=["agriculture", "shared"],
        examples=["crop plan for tomatoes this season"],
    )

    async def run(self, request: SkillRequest) -> SkillResult:
        task = self._task(request)
        crop = "crop"
        for c in ("tomato", "basil", "wheat", "corn", "lettuce", "pepper"):
            if c in task.lower():
                crop = c
                break
        stages = [
            ("Week 0", "Soil prep, irrigation layout, input plan"),
            ("Week 1–2", "Plant / transplant; establish moisture"),
            ("Week 3–6", "Vegetative care; scout pests twice weekly"),
            ("Week 6–12", "Flower/fruit support; steady nutrition"),
            ("Harvest+", "Pick window; yield log; residual cleanup"),
        ]
        lines = [f"**Crop Planning — {crop}**", ""]
        for when, what in stages:
            lines.append(f"- **{when}:** {what}")
        graph = [f for f in self._ctx_list(request, "graph_facts") if crop in f.lower() or "water" in f.lower()]
        if graph:
            lines += ["", "**Graph facts:**"] + [f"- {g}" for g in graph[:5]]
        lines.append("")
        lines.append("Adjust for frost dates and variety days-to-maturity.")
        return self._ok(
            "\n".join(lines),
            steps=[
                {"id": "s1", "title": "Crop select", "status": "done"},
                {"id": "s2", "title": "Stages", "status": "done"},
                {"id": "s3", "title": "Graph context", "status": "done"},
            ],
            data={"crop": crop},
            evidence=graph,
            confidence=0.74 if graph else 0.65,
            request=request,
        )

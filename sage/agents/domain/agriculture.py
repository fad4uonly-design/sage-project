"""Agriculture Agent — crop, soil, irrigation, pests, harvest, farm records."""

from __future__ import annotations

import re
from typing import Any

from sage.agents.domain_base import DomainAgent
from sage.agents.profile import AgentCapabilityProfile
from sage.agents.workflows.library import Workflow, WorkflowResult, WorkflowStep, new_workflow_id
from sage.decision.models import Criterion, DecisionOption, DecisionRequest


class AgricultureAgent(DomainAgent):
    profile = AgentCapabilityProfile(
        principal="agriculture_agent",
        domain="agriculture",
        display_name="Agriculture Agent",
        description="Crop management, irrigation, soil, pests, harvest, and farm planning",
        capabilities=[
            "crop",
            "soil",
            "irrigation",
            "fertilizer",
            "pest",
            "disease",
            "blight",
            "harvest",
            "greenhouse",
            "farm",
            "weather",
            "yield",
            "planting",
        ],
        tools=["calculator", "current_time"],
        permissions=["memory.read", "memory.write"],
        reasoning_strategies=["agriculture", "scientific", "risk", "planning"],
        workflows=[
            "wf_agriculture_diagnose_disease",
            "wf_agriculture_irrigation_plan",
            "wf_agriculture_fertilizer",
            "wf_agriculture_crop_calendar",
            "wf_agriculture_compare_methods",
        ],
        collaborate_with=["finance", "planning", "business"],
        confidence_threshold=0.3,
    )

    def register_workflows(self) -> None:
        self.workflows.register(
            Workflow(
                id=new_workflow_id("agriculture", "diagnose_disease"),
                name="Diagnose Crop Disease",
                domain="agriculture",
                description="Identify likely crop disease/pest and recommend actions",
                triggers=["disease", "blight", "pest", "diagnose", "infected", "spots", "wilting"],
                steps=[
                    WorkflowStep(id="s1", title="Identify crop & symptoms"),
                    WorkflowStep(id="s2", title="Query knowledge graph"),
                    WorkflowStep(id="s3", title="Rank likely causes"),
                    WorkflowStep(id="s4", title="Recommend treatments & prevention"),
                ],
                handler=self._wf_diagnose,
            )
        )
        self.workflows.register(
            Workflow(
                id=new_workflow_id("agriculture", "irrigation_plan"),
                name="Create Irrigation Plan",
                domain="agriculture",
                description="Build a practical irrigation schedule",
                triggers=["irrigation", "water schedule", "watering plan", "drip", "sprinkler"],
                steps=[
                    WorkflowStep(id="s1", title="Crop water needs"),
                    WorkflowStep(id="s2", title="Climate & soil factors"),
                    WorkflowStep(id="s3", title="Schedule design"),
                    WorkflowStep(id="s4", title="Cost/risk notes"),
                ],
                handler=self._wf_irrigation,
            )
        )
        self.workflows.register(
            Workflow(
                id=new_workflow_id("agriculture", "fertilizer"),
                name="Estimate Fertilizer Needs",
                domain="agriculture",
                description="Fertilizer recommendation from crop and soil cues",
                triggers=["fertilizer", "nutrient", "npk", "compost", "manure"],
                steps=[
                    WorkflowStep(id="s1", title="Crop nutrient profile"),
                    WorkflowStep(id="s2", title="Soil assumptions"),
                    WorkflowStep(id="s3", title="Application plan"),
                ],
                handler=self._wf_fertilizer,
            )
        )
        self.workflows.register(
            Workflow(
                id=new_workflow_id("agriculture", "crop_calendar"),
                name="Generate Crop Calendar",
                domain="agriculture",
                description="Seasonal calendar from planting to harvest",
                triggers=["calendar", "planting schedule", "crop calendar", "season plan", "when to plant"],
                steps=[
                    WorkflowStep(id="s1", title="Select crop"),
                    WorkflowStep(id="s2", title="Phenology stages"),
                    WorkflowStep(id="s3", title="Calendar output"),
                ],
                handler=self._wf_calendar,
            )
        )
        self.workflows.register(
            Workflow(
                id=new_workflow_id("agriculture", "compare_methods"),
                name="Compare Farming Methods",
                domain="agriculture",
                description="Multi-criteria comparison of farming approaches",
                triggers=["compare", "organic vs", "methods", "which method", "conventional"],
                steps=[
                    WorkflowStep(id="s1", title="Define options"),
                    WorkflowStep(id="s2", title="Score criteria"),
                    WorkflowStep(id="s3", title="Decision engine ranking"),
                ],
                handler=self._wf_compare_methods,
            )
        )

    async def enrich_domain_context(self, task: Any, ctx: dict[str, Any]) -> None:
        # Ensure crop entities exist when mentioned
        kg = ctx.get("kg")
        if not kg:
            return
        crops = re.findall(
            r"\b(tomato|tomatoes|basil|wheat|corn|rice|lettuce|pepper|cucumber|onion)\b",
            task.description,
            flags=re.I,
        )
        for crop in crops[:3]:
            name = crop.rstrip("s").title() if crop.lower().endswith("s") else crop.title()
            try:
                await kg.extract_and_merge(
                    f"{name} is a crop. {name} requires water. {name} requires soil.",
                    source="agriculture_agent",
                )
            except Exception:
                pass

    async def _wf_diagnose(self, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
        task = str(params.get("task") or ctx.get("task") or "")
        crop = _extract_crop(task) or "crop"
        symptoms = []
        for s in ("blight", "wilting", "spots", "yellow", "mold", "insects", "pest", "rot"):
            if s in task.lower():
                symptoms.append(s)

        facts = [f for f in ctx.get("graph_facts") or [] if crop.lower() in f.lower() or "blight" in f.lower()]
        steps = [
            {"id": "s1", "title": "Identify crop & symptoms", "status": "done", "detail": f"crop={crop}, symptoms={symptoms or ['unspecified']}"},
            {"id": "s2", "title": "Query knowledge graph", "status": "done", "detail": f"{len(facts)} facts"},
            {"id": "s3", "title": "Rank likely causes", "status": "done"},
            {"id": "s4", "title": "Recommend treatments", "status": "done"},
        ]

        causes = []
        if "blight" in task.lower() or "blight" in symptoms:
            causes.append(("Late/early blight", 0.75, "Fungal — humidity + leaf wetness"))
        if "wilting" in symptoms:
            causes.append(("Water stress or vascular wilt", 0.6, "Check soil moisture & roots"))
        if "pest" in symptoms or "insects" in symptoms:
            causes.append(("Insect pressure", 0.55, "Scout leaves (underside) at dawn"))
        if not causes:
            causes.append(("Environmental stress", 0.4, "Review water, heat, nutrients"))

        lines = [
            f"**Crop:** {crop.title()}",
            f"**Symptoms noted:** {', '.join(symptoms) if symptoms else 'general distress'}",
            "",
            "**Likely causes (ranked):**",
        ]
        for i, (name, conf, note) in enumerate(causes, 1):
            lines.append(f"{i}. {name} (conf ~{conf:.2f}) — {note}")
        if facts:
            lines += ["", "**Knowledge graph:**"]
            lines.extend(f"- {f}" for f in facts[:5])
        lines += [
            "",
            "**Immediate actions:**",
            "1. Isolate severely affected plants; remove heavily diseased tissue.",
            "2. Avoid overhead watering late day; improve airflow.",
            "3. Record date, weather, and photos in farm log.",
            "4. Re-check in 48h; escalate if spread accelerates.",
            "",
            "**Prevention:** resistant varieties, crop rotation, clean tools, balanced nutrition.",
        ]
        # Finance collab if cost mentioned
        data: dict[str, Any] = {"crop": crop, "causes": [c[0] for c in causes]}
        if any(w in task.lower() for w in ("cost", "budget", "expensive", "price")):
            data["collaborate"] = ["finance"]

        await self.remember(f"Agriculture diagnosis for {crop}: {causes[0][0]}", importance=0.65)
        return WorkflowResult(
            workflow_id="wf_agriculture_diagnose_disease",
            workflow_name="Diagnose Crop Disease",
            success=True,
            steps=steps,
            output="\n".join(lines),
            data=data,
        )

    async def _wf_irrigation(self, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
        task = str(params.get("task") or ctx.get("task") or "")
        crop = _extract_crop(task) or "general crops"
        heat = any(w in task.lower() for w in ("heat", "summer", "hot", "drought"))
        greenhouse = "greenhouse" in task.lower()

        morning = "05:30–07:00"
        evening = "none (prefer morning)" if not heat else "optional light pulse 18:00 if soil dry"
        freq = "daily" if heat else "every 2–3 days"
        method = "drip preferred" if greenhouse or "drip" in task.lower() else "drip or soaker hose"

        lines = [
            f"**Irrigation plan for:** {crop}",
            f"**Context:** {'high heat' if heat else 'moderate'}; {'greenhouse' if greenhouse else 'open field'}",
            "",
            "**Schedule:**",
            f"- Frequency: **{freq}**",
            f"- Primary window: **{morning}**",
            f"- Secondary: {evening}",
            f"- Method: {method}",
            "",
            "**Soil check:** finger test / moisture meter at 10–15 cm before watering.",
            "**Depth target:** wet root zone, avoid waterlogging (blight risk if leaves stay wet).",
            "",
            "**Weekly review:** adjust ±20% after rain or heat waves.",
        ]
        facts = [f for f in ctx.get("graph_facts") or [] if "water" in f.lower() or "irrigation" in f.lower()]
        if facts:
            lines += ["", "**Graph facts:**"]
            lines.extend(f"- {f}" for f in facts[:4])

        data: dict[str, Any] = {"crop": crop, "frequency": freq}
        if any(w in task.lower() for w in ("cost", "budget", "pump", "expense")):
            data["collaborate"] = ["finance"]
            lines += ["", "_Cost analysis requested — consulting Finance Agent…_"]

        return WorkflowResult(
            workflow_id="wf_agriculture_irrigation_plan",
            workflow_name="Create Irrigation Plan",
            success=True,
            steps=[
                {"id": "s1", "title": "Crop water needs", "status": "done"},
                {"id": "s2", "title": "Climate & soil factors", "status": "done"},
                {"id": "s3", "title": "Schedule design", "status": "done"},
                {"id": "s4", "title": "Cost/risk notes", "status": "done"},
            ],
            output="\n".join(lines),
            data=data,
        )

    async def _wf_fertilizer(self, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
        task = str(params.get("task") or ctx.get("task") or "")
        crop = _extract_crop(task) or "crop"
        lines = [
            f"**Fertilizer estimate for {crop.title()}**",
            "",
            "**Baseline (adjust with soil test):**",
            "- Nitrogen: moderate split applications (avoid excess → soft growth / disease).",
            "- Phosphorus: at planting / early root development.",
            "- Potassium: fruiting / stress resilience.",
            "",
            "**Organic options:** compost, well-rotted manure, mulch.",
            "**Application:** water-in after feed; avoid burning foliage.",
            "**Record:** product, rate, date, plot ID.",
        ]
        return WorkflowResult(
            workflow_id="wf_agriculture_fertilizer",
            workflow_name="Estimate Fertilizer Needs",
            success=True,
            steps=[
                {"id": "s1", "title": "Crop nutrient profile", "status": "done"},
                {"id": "s2", "title": "Soil assumptions", "status": "done"},
                {"id": "s3", "title": "Application plan", "status": "done"},
            ],
            output="\n".join(lines),
            data={"crop": crop, "collaborate": ["finance"] if "cost" in task.lower() else []},
        )

    async def _wf_calendar(self, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
        task = str(params.get("task") or ctx.get("task") or "")
        crop = _extract_crop(task) or "tomato"
        # Generic temperate-leaning calendar
        stages = [
            ("Week 0", "Soil prep, amend organic matter, plan irrigation"),
            ("Week 1–2", "Start seeds / transplant hardened seedlings"),
            ("Week 3–5", "Establish roots; light feeding; stake/trellis"),
            ("Week 6–10", "Vegetative growth; pest scouting twice weekly"),
            ("Week 10–14", "Flowering/fruit set; steady water; potassium focus"),
            ("Week 12–16+", "Harvest window; successive picks; record yield"),
        ]
        lines = [f"**Crop calendar — {crop.title()}**", ""]
        for when, what in stages:
            lines.append(f"- **{when}:** {what}")
        lines += ["", "Adjust for local frost dates and variety days-to-maturity."]
        # Graph harvested_after if present
        for f in ctx.get("graph_facts") or []:
            if "harvest" in f.lower():
                lines.append(f"- Graph: {f}")
        return WorkflowResult(
            workflow_id="wf_agriculture_crop_calendar",
            workflow_name="Generate Crop Calendar",
            success=True,
            steps=[
                {"id": "s1", "title": "Select crop", "status": "done"},
                {"id": "s2", "title": "Phenology stages", "status": "done"},
                {"id": "s3", "title": "Calendar output", "status": "done"},
            ],
            output="\n".join(lines),
            data={"crop": crop},
        )

    async def _wf_compare_methods(self, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
        task = str(params.get("task") or ctx.get("task") or "")
        options = [
            DecisionOption(
                id="organic",
                name="Organic",
                description="Organic inputs, biological pest control",
                scores={"yield": 0.55, "cost": 0.45, "sustainability": 0.9, "risk": 0.5},
                risks=["Certification overhead", "Pest outbreaks"],
            ),
            DecisionOption(
                id="conventional",
                name="Conventional",
                description="Synthetic fertilizers/pesticides as needed",
                scores={"yield": 0.85, "cost": 0.7, "sustainability": 0.4, "risk": 0.45},
                risks=["Input price spikes", "Resistance"],
            ),
            DecisionOption(
                id="integrated",
                name="Integrated (IPM)",
                description="Hybrid: soil health + targeted interventions",
                scores={"yield": 0.75, "cost": 0.65, "sustainability": 0.75, "risk": 0.35},
                risks=["Requires scouting skill"],
            ),
        ]
        req = DecisionRequest(
            question=task or "Which farming method should I use?",
            criteria=[
                Criterion(id="yield", name="Yield potential", weight=0.3),
                Criterion(id="cost", name="Cost efficiency", weight=0.25),
                Criterion(id="sustainability", name="Sustainability", weight=0.25),
                Criterion(id="risk", name="Operational risk", weight=0.2, maximize=False),
            ],
            options=options,
        )
        decision = await self.decide(req)
        output = decision.format() if decision else "Decision engine unavailable."
        return WorkflowResult(
            workflow_id="wf_agriculture_compare_methods",
            workflow_name="Compare Farming Methods",
            success=True,
            steps=[
                {"id": "s1", "title": "Define options", "status": "done"},
                {"id": "s2", "title": "Score criteria", "status": "done"},
                {"id": "s3", "title": "Decision engine ranking", "status": "done"},
            ],
            output=output,
            data={"decision_id": decision.request_id if decision else None},
        )


def _extract_crop(text: str) -> str | None:
    m = re.search(
        r"\b(tomatoes|tomato|basil|wheat|corn|rice|lettuce|peppers|pepper|"
        r"cucumbers|cucumber|onions|onion|herbs|herb)\b",
        text,
        flags=re.I,
    )
    if not m:
        return None
    w = m.group(1).lower()
    irregular = {
        "tomatoes": "tomato",
        "peppers": "pepper",
        "cucumbers": "cucumber",
        "onions": "onion",
        "herbs": "herb",
    }
    return irregular.get(w, w)

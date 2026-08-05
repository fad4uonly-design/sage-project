"""Business Strategy Agent."""

from __future__ import annotations

from typing import Any

from sage.agents.domain_base import DomainAgent
from sage.agents.profile import AgentCapabilityProfile
from sage.agents.workflows.library import Workflow, WorkflowResult, WorkflowStep, new_workflow_id
from sage.decision.models import Criterion, DecisionOption, DecisionRequest


class BusinessAgent(DomainAgent):
    profile = AgentCapabilityProfile(
        principal="business_agent",
        domain="business",
        display_name="Business Strategy Agent",
        description="SWOT, planning, marketing, pricing, KPIs, competitor framing",
        capabilities=[
            "strategy",
            "swot",
            "market",
            "marketing",
            "pricing",
            "competitor",
            "kpi",
            "business plan",
            "customer",
            "sales",
            "operations",
            "go-to-market",
        ],
        tools=[],
        permissions=["memory.read", "memory.write"],
        reasoning_strategies=["business", "decision", "planning", "risk"],
        workflows=[
            "wf_business_swot",
            "wf_business_plan",
            "wf_business_pricing",
            "wf_business_kpi",
            "wf_business_gtm",
        ],
        collaborate_with=["finance", "agriculture", "programming", "planning"],
        confidence_threshold=0.3,
    )

    def register_workflows(self) -> None:
        self.workflows.register(
            Workflow(
                id=new_workflow_id("business", "swot"),
                name="SWOT Analysis",
                domain="business",
                description="Structured SWOT for a venture or product",
                triggers=["swot", "strengths", "weaknesses", "opportunities", "threats"],
                steps=[
                    WorkflowStep(id="s1", title="Context"),
                    WorkflowStep(id="s2", title="Four quadrants"),
                    WorkflowStep(id="s3", title="Strategic moves"),
                ],
                handler=self._wf_swot,
            )
        )
        self.workflows.register(
            Workflow(
                id=new_workflow_id("business", "plan"),
                name="Business Planning",
                domain="business",
                description="Lightweight business plan outline",
                triggers=["business plan", "business planning", "venture plan"],
                steps=[
                    WorkflowStep(id="s1", title="Problem & customer"),
                    WorkflowStep(id="s2", title="Offer & model"),
                    WorkflowStep(id="s3", title="Go-to-market & metrics"),
                ],
                handler=self._wf_plan,
            )
        )
        self.workflows.register(
            Workflow(
                id=new_workflow_id("business", "pricing"),
                name="Pricing Strategy",
                domain="business",
                description="Compare pricing approaches",
                triggers=["pricing", "price point", "how much to charge", "subscription price"],
                steps=[
                    WorkflowStep(id="s1", title="Options"),
                    WorkflowStep(id="s2", title="Decision scores"),
                    WorkflowStep(id="s3", title="Recommendation"),
                ],
                handler=self._wf_pricing,
            )
        )
        self.workflows.register(
            Workflow(
                id=new_workflow_id("business", "kpi"),
                name="KPI Monitoring Setup",
                domain="business",
                description="Define a minimal KPI set",
                triggers=["kpi", "metrics", "dashboard", "okrs"],
                steps=[
                    WorkflowStep(id="s1", title="North star"),
                    WorkflowStep(id="s2", title="Input metrics"),
                    WorkflowStep(id="s3", title="Cadence"),
                ],
                handler=self._wf_kpi,
            )
        )
        self.workflows.register(
            Workflow(
                id=new_workflow_id("business", "gtm"),
                name="Go-to-Market",
                domain="business",
                description="GTM motion sketch",
                triggers=["go-to-market", "gtm", "launch plan", "marketing strategy"],
                steps=[
                    WorkflowStep(id="s1", title="Audience"),
                    WorkflowStep(id="s2", title="Channels"),
                    WorkflowStep(id="s3", title="Message & loop"),
                ],
                handler=self._wf_gtm,
            )
        )

    async def _wf_swot(self, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
        task = str(params.get("task") or ctx.get("task") or "")
        subject = task[:120]
        farm = any(w in task.lower() for w in ("farm", "crop", "agriculture", "produce"))
        strengths = ["Local knowledge", "Direct customer access"]
        weaknesses = ["Limited capital", "Brand awareness"]
        opportunities = ["Premium / organic niche", "Direct-to-consumer channels"]
        threats = ["Weather volatility", "Input cost inflation", "Larger competitors"]
        if farm:
            strengths.append("Land / growing capability")
            opportunities.append("Farm-to-table partnerships")
            threats.append("Disease / pest pressure")
        lines = [
            f"**SWOT —** {subject}",
            "",
            "**Strengths**",
            *[f"- {x}" for x in strengths],
            "",
            "**Weaknesses**",
            *[f"- {x}" for x in weaknesses],
            "",
            "**Opportunities**",
            *[f"- {x}" for x in opportunities],
            "",
            "**Threats**",
            *[f"- {x}" for x in threats],
            "",
            "**Strategic moves**",
            "1. Double-down on strengths that map to opportunities.",
            "2. Pair each threat with a mitigation (insurance, diversification, cash buffer).",
            "3. Time-box one weakness improvement this quarter.",
        ]
        data: dict[str, Any] = {}
        if farm:
            data["collaborate"] = ["agriculture", "finance"]
        return WorkflowResult(
            workflow_id="wf_business_swot",
            workflow_name="SWOT Analysis",
            success=True,
            steps=[
                {"id": "s1", "title": "Context", "status": "done"},
                {"id": "s2", "title": "Four quadrants", "status": "done"},
                {"id": "s3", "title": "Strategic moves", "status": "done"},
            ],
            output="\n".join(lines),
            data=data,
        )

    async def _wf_plan(self, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
        task = str(params.get("task") or ctx.get("task") or "")
        plan_text = await self.plan(task, ctx)
        lines = [
            "**Business plan (lean)**",
            "",
            "1. **Problem & customer** — who hurts and how urgently?",
            "2. **Offer** — product/service + proof of value.",
            "3. **Model** — price, costs, margin hypothesis.",
            "4. **GTM** — first channel to 10 paying customers.",
            "5. **Operations** — delivery capacity & quality bar.",
            "6. **Metrics** — weekly leading indicators.",
            "7. **Risks** — top 3 kill-shots and early warnings.",
            "",
            plan_text or "",
        ]
        return WorkflowResult(
            workflow_id="wf_business_plan",
            workflow_name="Business Planning",
            success=True,
            steps=[
                {"id": "s1", "title": "Problem & customer", "status": "done"},
                {"id": "s2", "title": "Offer & model", "status": "done"},
                {"id": "s3", "title": "Go-to-market & metrics", "status": "done"},
            ],
            output="\n".join(lines),
            data={"collaborate": ["finance"]},
        )

    async def _wf_pricing(self, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
        task = str(params.get("task") or ctx.get("task") or "")
        opts = [
            DecisionOption(
                id="cost_plus",
                name="Cost-plus",
                scores={"margin": 0.7, "simplicity": 0.9, "market_fit": 0.45},
                risks=["Ignores willingness to pay"],
            ),
            DecisionOption(
                id="value",
                name="Value-based",
                scores={"margin": 0.85, "simplicity": 0.4, "market_fit": 0.8},
                risks=["Needs customer insight"],
            ),
            DecisionOption(
                id="penetration",
                name="Penetration (low entry)",
                scores={"margin": 0.35, "simplicity": 0.7, "market_fit": 0.75},
                risks=["Hard to raise price later", "Cash strain"],
            ),
        ]
        req = DecisionRequest(
            question=task or "Which pricing strategy fits?",
            criteria=[
                Criterion(id="margin", name="Margin potential", weight=0.4),
                Criterion(id="simplicity", name="Simplicity", weight=0.2),
                Criterion(id="market_fit", name="Market fit", weight=0.4),
            ],
            options=opts,
        )
        decision = await self.decide(req)
        return WorkflowResult(
            workflow_id="wf_business_pricing",
            workflow_name="Pricing Strategy",
            success=True,
            steps=[
                {"id": "s1", "title": "Options", "status": "done"},
                {"id": "s2", "title": "Decision scores", "status": "done"},
                {"id": "s3", "title": "Recommendation", "status": "done"},
            ],
            output=decision.format() if decision else "",
            data={"collaborate": ["finance"]},
        )

    async def _wf_kpi(self, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
        lines = [
            "**KPI starter set**",
            "",
            "- **North star:** weekly engaged paying customers (or kg sold / margin $)",
            "- **Acquisition:** leads → trials → paid conversion",
            "- **Retention:** repeat purchase rate / churn",
            "- **Unit economics:** contribution margin per order",
            "- **Ops:** on-time delivery %, defect/return rate",
            "",
            "**Cadence:** weekly 30-min review; monthly deep dive; one experiment at a time.",
        ]
        return WorkflowResult(
            workflow_id="wf_business_kpi",
            workflow_name="KPI Monitoring Setup",
            success=True,
            steps=[
                {"id": "s1", "title": "North star", "status": "done"},
                {"id": "s2", "title": "Input metrics", "status": "done"},
                {"id": "s3", "title": "Cadence", "status": "done"},
            ],
            output="\n".join(lines),
            data={},
        )

    async def _wf_gtm(self, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
        lines = [
            "**Go-to-market sketch**",
            "",
            "1. **Beachhead customer** — specific persona with budget & urgency.",
            "2. **Promise** — one-sentence outcome you can prove.",
            "3. **Channel** — pick ONE primary (direct sales, market stall, Instagram, B2B outreach).",
            "4. **Offer design** — entry SKU + clear next step.",
            "5. **Feedback loop** — talk to 5 customers/week; ship weekly improvements.",
            "6. **Kill criteria** — what evidence stops this channel in 30 days.",
        ]
        return WorkflowResult(
            workflow_id="wf_business_gtm",
            workflow_name="Go-to-Market",
            success=True,
            steps=[
                {"id": "s1", "title": "Audience", "status": "done"},
                {"id": "s2", "title": "Channels", "status": "done"},
                {"id": "s3", "title": "Message & loop", "status": "done"},
            ],
            output="\n".join(lines),
            data={},
        )

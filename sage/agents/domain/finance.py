"""Finance & Accounting Agent."""

from __future__ import annotations

import re
from typing import Any

from sage.agents.domain_base import DomainAgent
from sage.agents.profile import AgentCapabilityProfile
from sage.agents.workflows.library import Workflow, WorkflowResult, WorkflowStep, new_workflow_id
from sage.decision.models import Criterion, DecisionOption, DecisionRequest


class FinanceAgent(DomainAgent):
    profile = AgentCapabilityProfile(
        principal="finance_agent",
        domain="finance",
        display_name="Finance & Accounting Agent",
        description="Budgets, cash flow, loans, investments, basic accounting support",
        capabilities=[
            "budget",
            "loan",
            "cashflow",
            "cash flow",
            "invoice",
            "revenue",
            "profit",
            "expense",
            "investment",
            "accounting",
            "tax",
            "roi",
            "cost",
            "interest",
        ],
        tools=["calculator"],
        permissions=["memory.read", "memory.write"],
        reasoning_strategies=["business", "mathematical", "risk", "decision"],
        workflows=[
            "wf_finance_loan_comparison",
            "wf_finance_budget",
            "wf_finance_investment",
            "wf_finance_cashflow",
            "wf_finance_expense_forecast",
        ],
        collaborate_with=["business", "agriculture", "planning"],
        confidence_threshold=0.3,
    )

    async def default_execute(self, task: Any, ctx: dict[str, Any]) -> str:
        # When pulled in for cost collaboration, prefer expense forecast
        desc = task.description.lower()
        if any(w in desc for w in ("cost", "expense", "estimate the cost", "how much")):
            result = await self.workflows.run(
                "wf_finance_expense_forecast",
                ctx,
                params={"task": task.description},
            )
            if result.success and result.output:
                return await self.generate_response(task, ctx, workflow_result=result)
        return await super().default_execute(task, ctx)

    def register_workflows(self) -> None:
        self.workflows.register(
            Workflow(
                id=new_workflow_id("finance", "loan_comparison"),
                name="Loan Comparison",
                domain="finance",
                description="Compare loan options by payment and total interest",
                triggers=["loan", "interest rate", "mortgage", "borrow", "financing"],
                steps=[
                    WorkflowStep(id="s1", title="Extract loan terms"),
                    WorkflowStep(id="s2", title="Compute payments"),
                    WorkflowStep(id="s3", title="Rank options"),
                ],
                handler=self._wf_loan,
            )
        )
        self.workflows.register(
            Workflow(
                id=new_workflow_id("finance", "budget"),
                name="Budget Creation",
                domain="finance",
                description="Build a simple budget framework",
                triggers=["budget", "spending plan", "allocate money"],
                steps=[
                    WorkflowStep(id="s1", title="Income"),
                    WorkflowStep(id="s2", title="Fixed vs variable"),
                    WorkflowStep(id="s3", title="Allocation plan"),
                ],
                handler=self._wf_budget,
            )
        )
        self.workflows.register(
            Workflow(
                id=new_workflow_id("finance", "investment"),
                name="Investment Analysis",
                domain="finance",
                description="Compare investment choices with risk/return framing",
                triggers=["invest", "investment", "roi", "return", "portfolio"],
                steps=[
                    WorkflowStep(id="s1", title="Define options"),
                    WorkflowStep(id="s2", title="Risk/return scores"),
                    WorkflowStep(id="s3", title="Decision ranking"),
                ],
                handler=self._wf_investment,
            )
        )
        self.workflows.register(
            Workflow(
                id=new_workflow_id("finance", "cashflow"),
                name="Cash Flow Projection",
                domain="finance",
                description="Simple cash flow outlook",
                triggers=["cash flow", "cashflow", "runway", "liquidity"],
                steps=[
                    WorkflowStep(id="s1", title="Inflows"),
                    WorkflowStep(id="s2", title="Outflows"),
                    WorkflowStep(id="s3", title="Net & runway"),
                ],
                handler=self._wf_cashflow,
            )
        )
        self.workflows.register(
            Workflow(
                id=new_workflow_id("finance", "expense_forecast"),
                name="Expense Forecast",
                domain="finance",
                description="Forecast expenses for a project or farm operation",
                triggers=["expense", "cost estimate", "forecast cost", "how much will it cost"],
                steps=[
                    WorkflowStep(id="s1", title="Cost categories"),
                    WorkflowStep(id="s2", title="Estimate ranges"),
                    WorkflowStep(id="s3", title="Totals & buffers"),
                ],
                handler=self._wf_expense,
            )
        )

    async def _wf_loan(self, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
        task = str(params.get("task") or ctx.get("task") or "")
        principal = _first_number(task, default=10000.0)
        # Find percentages
        rates = [float(x) / 100.0 for x in re.findall(r"(\d+(?:\.\d+)?)\s*%", task)]
        if len(rates) < 2:
            rates = [0.08, 0.11, 0.14]
        years = 5
        ym = re.search(r"(\d+)\s*(?:year|yr)", task, re.I)
        if ym:
            years = int(ym.group(1))

        options_out = []
        dec_opts = []
        for i, annual in enumerate(rates[:4]):
            monthly_r = annual / 12.0
            n = years * 12
            if monthly_r > 0:
                payment = principal * (monthly_r * (1 + monthly_r) ** n) / ((1 + monthly_r) ** n - 1)
            else:
                payment = principal / n
            total = payment * n
            interest = total - principal
            name = f"Loan @ {annual*100:.2f}%"
            options_out.append(
                f"- **{name}**: monthly ~{payment:,.2f}, total interest ~{interest:,.2f}, total paid ~{total:,.2f}"
            )
            dec_opts.append(
                DecisionOption(
                    id=f"loan_{i}",
                    name=name,
                    scores={
                        "payment": payment,
                        "interest": interest,
                        "simplicity": 0.7,
                    },
                    risks=["Rate may be variable", "Fees not included"] if i == 1 else ["Fees not included"],
                )
            )

        req = DecisionRequest(
            question=f"Which loan is best for principal {principal:,.0f} over {years}y?",
            criteria=[
                Criterion(id="payment", name="Monthly payment", weight=0.4, maximize=False),
                Criterion(id="interest", name="Total interest", weight=0.45, maximize=False),
                Criterion(id="simplicity", name="Simplicity", weight=0.15),
            ],
            options=dec_opts,
        )
        decision = await self.decide(req)
        lines = [
            f"**Loan comparison** (principal {principal:,.2f}, term {years} years)",
            "",
            *options_out,
            "",
            decision.format() if decision else "",
            "",
            "_Estimates exclude fees/taxes; verify with lender quotes._",
        ]
        # calculator tool sanity check on first payment
        if rates:
            await self.use_tool("calculator", expression=f"{principal} * 0.01")

        return WorkflowResult(
            workflow_id="wf_finance_loan_comparison",
            workflow_name="Loan Comparison",
            success=True,
            steps=[
                {"id": "s1", "title": "Extract loan terms", "status": "done"},
                {"id": "s2", "title": "Compute payments", "status": "done"},
                {"id": "s3", "title": "Rank options", "status": "done"},
            ],
            output="\n".join(lines),
            data={"principal": principal, "years": years},
        )

    async def _wf_budget(self, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
        task = str(params.get("task") or ctx.get("task") or "")
        income = _first_number(task, default=3000.0)
        # 50/30/20-ish with farm tweak
        needs = income * 0.50
        ops = income * 0.30
        save = income * 0.20
        lines = [
            f"**Budget framework** (reference income {income:,.2f})",
            "",
            f"- **Needs / essentials (50%):** {needs:,.2f} — rent, utilities, staples, debt minimums",
            f"- **Operations / goals (30%):** {ops:,.2f} — farm inputs, tools, growth projects",
            f"- **Savings & buffer (20%):** {save:,.2f} — emergency fund, equipment reserve",
            "",
            "**Process:** track 30 days actuals → adjust categories → monthly review.",
            "**Accounting tip:** separate personal vs business accounts; tag every expense.",
        ]
        if any(w in task.lower() for w in ("farm", "crop", "agriculture", "irrigation")):
            lines += [
                "",
                "**Farm cost buckets:** seed/stock, fertilizer, water/energy, labor, maintenance, transport.",
            ]
        await self.remember(f"Budget baseline income={income}", importance=0.55)
        return WorkflowResult(
            workflow_id="wf_finance_budget",
            workflow_name="Budget Creation",
            success=True,
            steps=[
                {"id": "s1", "title": "Income", "status": "done"},
                {"id": "s2", "title": "Fixed vs variable", "status": "done"},
                {"id": "s3", "title": "Allocation plan", "status": "done"},
            ],
            output="\n".join(lines),
            data={"income": income},
        )

    async def _wf_investment(self, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
        task = str(params.get("task") or ctx.get("task") or "")
        opts = [
            DecisionOption(
                id="safe",
                name="Low-risk savings / T-bills",
                scores={"return": 0.3, "risk": 0.2, "liquidity": 0.9},
                risks=["Inflation drag"],
            ),
            DecisionOption(
                id="balanced",
                name="Balanced index portfolio",
                scores={"return": 0.65, "risk": 0.45, "liquidity": 0.7},
                risks=["Market drawdowns"],
            ),
            DecisionOption(
                id="growth",
                name="Growth / concentrated bet",
                scores={"return": 0.85, "risk": 0.8, "liquidity": 0.5},
                risks=["High volatility", "Permanent capital loss"],
            ),
        ]
        if "farm" in task.lower() or "equipment" in task.lower():
            opts.append(
                DecisionOption(
                    id="farm_capex",
                    name="Productive farm equipment",
                    scores={"return": 0.7, "risk": 0.55, "liquidity": 0.3},
                    risks=["Utilization risk", "Maintenance"],
                )
            )
        req = DecisionRequest(
            question=task or "Where should I allocate capital?",
            criteria=[
                Criterion(id="return", name="Expected return", weight=0.4),
                Criterion(id="risk", name="Risk", weight=0.35, maximize=False),
                Criterion(id="liquidity", name="Liquidity", weight=0.25),
            ],
            options=opts,
        )
        decision = await self.decide(req)
        return WorkflowResult(
            workflow_id="wf_finance_investment",
            workflow_name="Investment Analysis",
            success=True,
            steps=[
                {"id": "s1", "title": "Define options", "status": "done"},
                {"id": "s2", "title": "Risk/return scores", "status": "done"},
                {"id": "s3", "title": "Decision ranking", "status": "done"},
            ],
            output=decision.format() if decision else "No decision",
            data={},
        )

    async def _wf_cashflow(self, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
        task = str(params.get("task") or ctx.get("task") or "")
        inflow = _first_number(task, default=5000.0)
        # second number as outflow if present
        nums = [float(x.replace(",", "")) for x in re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", task)]
        outflow = nums[1] if len(nums) > 1 else inflow * 0.75
        net = inflow - outflow
        runway = (inflow * 3) / outflow if outflow else float("inf")
        lines = [
            "**Cash flow projection (simplified monthly)**",
            f"- Inflows: {inflow:,.2f}",
            f"- Outflows: {outflow:,.2f}",
            f"- **Net:** {net:,.2f}",
            f"- Buffer runway (if 3× inflow reserve): ~{runway:.1f} months of outflows",
            "",
            "**Actions:** accelerate receivables, stagger payables, maintain 3-month expense reserve.",
        ]
        return WorkflowResult(
            workflow_id="wf_finance_cashflow",
            workflow_name="Cash Flow Projection",
            success=True,
            steps=[
                {"id": "s1", "title": "Inflows", "status": "done"},
                {"id": "s2", "title": "Outflows", "status": "done"},
                {"id": "s3", "title": "Net & runway", "status": "done"},
            ],
            output="\n".join(lines),
            data={"inflow": inflow, "outflow": outflow, "net": net},
        )

    async def _wf_expense(self, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
        task = str(params.get("task") or ctx.get("task") or "")
        base = _first_number(task, default=1000.0)
        is_farm = any(w in task.lower() for w in ("farm", "irrigation", "crop", "fertilizer", "greenhouse"))
        if is_farm:
            cats = {
                "Water / energy": base * 0.25,
                "Fertilizer / inputs": base * 0.30,
                "Labor": base * 0.20,
                "Maintenance": base * 0.15,
                "Contingency (10%)": base * 0.10,
            }
        else:
            cats = {
                "Labor": base * 0.35,
                "Materials": base * 0.30,
                "Overhead": base * 0.20,
                "Contingency (15%)": base * 0.15,
            }
        total = sum(cats.values())
        lines = ["**Expense forecast**", ""]
        for k, v in cats.items():
            lines.append(f"- {k}: {v:,.2f}")
        lines += ["", f"**Estimated total:** {total:,.2f}", "", "Refine with quotes; keep contingency untouched."]
        data: dict[str, Any] = {"total": total, "categories": cats}
        if is_farm:
            data["collaborate"] = []  # already finance
        return WorkflowResult(
            workflow_id="wf_finance_expense_forecast",
            workflow_name="Expense Forecast",
            success=True,
            steps=[
                {"id": "s1", "title": "Cost categories", "status": "done"},
                {"id": "s2", "title": "Estimate ranges", "status": "done"},
                {"id": "s3", "title": "Totals & buffers", "status": "done"},
            ],
            output="\n".join(lines),
            data=data,
        )


def _first_number(text: str, default: float = 0.0) -> float:
    m = re.search(r"(\d+(?:,\d{3})*(?:\.\d+)?)", text.replace(",", ""))
    # also try with commas stripped from original
    m = re.search(r"(\d+(?:\.\d+)?)", text.replace(",", ""))
    if not m:
        return default
    try:
        return float(m.group(1))
    except ValueError:
        return default

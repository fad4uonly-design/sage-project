"""Reusable Business Intelligence workflow handlers (v0.3.1)."""

from __future__ import annotations

import re
from typing import Any, Callable

from sage.agents.workflows.library import Workflow, WorkflowResult, WorkflowStep, new_workflow_id
from sage.decision.models import Criterion, DecisionOption, DecisionRequest

Handler = Callable[[Any, dict[str, Any], dict[str, Any]], Any]


def _task(params: dict[str, Any], ctx: dict[str, Any]) -> str:
    return str(params.get("task") or ctx.get("task") or "")


def _num(text: str, default: float = 0.0) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)", text.replace(",", ""))
    return float(m.group(1)) if m else default


def _facts(ctx: dict[str, Any], *keys: str) -> list[str]:
    out = []
    for f in ctx.get("graph_facts") or []:
        fl = f.lower()
        if any(k in fl for k in keys) or not keys:
            out.append(f)
    return out[:8]


def _steps(*titles: str) -> list[dict[str, Any]]:
    return [{"id": f"s{i+1}", "title": t, "status": "done"} for i, t in enumerate(titles)]


def _result(
    wf_id: str,
    name: str,
    output: str,
    steps: list[dict[str, Any]],
    data: dict[str, Any] | None = None,
) -> WorkflowResult:
    return WorkflowResult(
        workflow_id=wf_id,
        workflow_name=name,
        success=True,
        steps=steps,
        output=output,
        data=data or {},
    )


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


async def wf_business_plan(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    plan = await agent.plan(task, ctx)
    lines = [
        "**Business Plan (lean canvas style)**",
        f"_Focus:_ {task[:160]}",
        "",
        "1. **Problem & customer** — who hurts, how urgently, willingness to pay?",
        "2. **Value proposition** — outcome you can prove in one sentence.",
        "3. **Offer & channels** — product/service + first distribution path.",
        "4. **Revenue model** — price, unit economics, payment terms.",
        "5. **Cost structure** — fixed vs variable; break-even sketch.",
        "6. **Key metrics** — weekly leading indicators.",
        "7. **Risks & moats** — top 3 kill-shots and early warnings.",
        "",
        plan or "",
    ]
    facts = _facts(ctx, "company", "customer", "market", "product")
    if facts:
        lines += ["", "**Knowledge graph:**"] + [f"- {f}" for f in facts]
    return _result(
        "wf_business_create_plan",
        "Create Business Plan",
        "\n".join(lines),
        _steps("Context", "Canvas sections", "Plan steps", "Graph evidence"),
        {"collaborate": ["finance", "strategy"]},
    )


async def wf_startup_planning(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    lines = [
        "**Startup Planning**",
        f"_Venture:_ {task[:160]}",
        "",
        "**Phase 0 — Validate (2–4 weeks)**",
        "- 15–25 customer interviews; problem score ≥ 8/10 for beachhead",
        "- Fake-door or concierge MVP; define kill criteria",
        "",
        "**Phase 1 — Build (4–8 weeks)**",
        "- Smallest sellable wedge; instrumentation on day one",
        "- Founding team roles: product, distribution, ops",
        "",
        "**Phase 2 — Traction**",
        "- One primary channel until 10–50 paying customers",
        "- Unit economics: CAC, contribution margin, payback",
        "",
        "**Capital:** bootstrap vs seed — only raise against a proven wedge.",
    ]
    return _result(
        "wf_business_startup_planning",
        "Startup Planning",
        "\n".join(lines),
        _steps("Validate", "Build", "Traction", "Capital"),
        {"collaborate": ["finance", "marketing", "sales"]},
    )


async def wf_expansion_planning(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    lines = [
        "**Expansion Planning**",
        f"_Scope:_ {task[:160]}",
        "",
        "1. **Where to expand** — geo / segment / product adjacency scorecard",
        "2. **Why now** — demand signal, capacity, competitive window",
        "3. **How** — organic, partnership, acquisition, franchise",
        "4. **Resourcing** — headcount, capital, inventory, systems",
        "5. **Risk gates** — regulatory, supply, brand dilution",
        "6. **90-day pilot** — success metrics before full rollout",
    ]
    return _result(
        "wf_business_expansion_planning",
        "Expansion Planning",
        "\n".join(lines),
        _steps("Target", "Mode", "Resources", "Pilot"),
        {"collaborate": ["finance", "operations", "risk_compliance"]},
    )


async def wf_business_model(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    opts = [
        DecisionOption(
            id="sub",
            name="Subscription / recurring",
            scores={"predictability": 0.9, "margin": 0.7, "complexity": 0.5},
            risks=["Churn", "Support load"],
        ),
        DecisionOption(
            id="tx",
            name="Transactional / one-off",
            scores={"predictability": 0.4, "margin": 0.65, "complexity": 0.8},
            risks=["Demand spikes", "Reacquisition cost"],
        ),
        DecisionOption(
            id="hybrid",
            name="Hybrid (base + usage)",
            scores={"predictability": 0.75, "margin": 0.75, "complexity": 0.45},
            risks=["Pricing complexity"],
        ),
        DecisionOption(
            id="marketplace",
            name="Marketplace / take-rate",
            scores={"predictability": 0.55, "margin": 0.85, "complexity": 0.3},
            risks=["Cold start", "Trust & quality"],
        ),
    ]
    req = DecisionRequest(
        question=task or "Which business model fits?",
        criteria=[
            Criterion(id="predictability", name="Revenue predictability", weight=0.35),
            Criterion(id="margin", name="Margin potential", weight=0.35),
            Criterion(id="complexity", name="Operational simplicity", weight=0.3),
        ],
        options=opts,
    )
    decision = await agent.decide(req)
    return _result(
        "wf_business_model_analysis",
        "Business Model Analysis",
        decision.format() if decision else "Decision engine unavailable.",
        _steps("Options", "Score", "Recommend"),
        {"collaborate": ["finance"]},
    )


async def wf_feasibility(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    lines = [
        "**Feasibility Study**",
        f"_Idea:_ {task[:160]}",
        "",
        "| Lens | Questions | Go/No-Go signals |",
        "|---|---|---|",
        "| Market | Size, growth, urgency? | ≥ identifiable beachhead |",
        "| Technical | Can we deliver quality? | MVP path < 90 days |",
        "| Financial | Unit economics path? | Path to positive contribution |",
        "| Legal/ops | Licenses, supply, talent? | No blocking constraint |",
        "| Strategic | Fits mission & strengths? | Aligns with core capabilities |",
        "",
        "**Output:** scored recommendation + open questions list.",
    ]
    return _result(
        "wf_business_feasibility",
        "Feasibility Study",
        "\n".join(lines),
        _steps("Lenses", "Signals", "Recommendation"),
        {"collaborate": ["finance", "risk_compliance", "operations"]},
    )


# ---------------------------------------------------------------------------
# Marketing
# ---------------------------------------------------------------------------


async def wf_marketing_plan(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    lines = [
        "**Marketing Plan**",
        f"_Brief:_ {task[:160]}",
        "",
        "1. **Audience** — primary persona, pains, jobs-to-be-done",
        "2. **Positioning** — category, contrast, proof",
        "3. **Message house** — one promise + 3 proof pillars",
        "4. **Channels** — pick 1–2 primary; kill criteria at day 30",
        "5. **Content / campaigns** — cadence and offers",
        "6. **Budget & KPIs** — CAC proxy, CTR, conversion, pipeline $",
        "7. **Feedback loop** — weekly creative + channel review",
    ]
    facts = _facts(ctx, "campaign", "customer", "market", "brand")
    if facts:
        lines += ["", "**Graph:**"] + [f"- {f}" for f in facts]
    return _result(
        "wf_marketing_plan",
        "Marketing Plan",
        "\n".join(lines),
        _steps("Audience", "Positioning", "Channels", "KPIs"),
        {"collaborate": ["sales", "analytics", "finance"]},
    )


async def wf_segmentation(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    lines = [
        "**Customer Segmentation**",
        f"_Context:_ {task[:140]}",
        "",
        "| Segment | Need | Willingness | Reachability | Priority |",
        "|---|---|---|---|---|",
        "| Beachhead A | Acute pain | High | Direct | P0 |",
        "| Adjacent B | Moderate | Medium | Partner | P1 |",
        "| Broad C | Latent | Low | Mass | P2 / later |",
        "",
        "**Rule:** dominate one segment before expanding messaging.",
    ]
    return _result(
        "wf_marketing_segmentation",
        "Customer Segmentation",
        "\n".join(lines),
        _steps("Axes", "Segments", "Priority"),
        {},
    )


async def wf_campaign(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    budget = _num(task, 1000.0)
    lines = [
        "**Campaign Planning**",
        f"_Brief:_ {task[:140]}",
        f"_Reference budget:_ {budget:,.0f}",
        "",
        f"- Creative tests: 3 hooks × 2 formats (~{budget*0.25:,.0f})",
        f"- Media / distribution (~{budget*0.55:,.0f})",
        f"- Landing / ops / tools (~{budget*0.15:,.0f})",
        f"- Contingency (~{budget*0.05:,.0f})",
        "",
        "**KPIs:** CTR, CPC/CPM, conversion, cost per lead, pipeline influenced.",
        "**Cadence:** daily spend check, mid-campaign creative kill, post-mortem.",
    ]
    return _result(
        "wf_marketing_campaign",
        "Campaign Planning",
        "\n".join(lines),
        _steps("Budget split", "Creative", "KPIs"),
        {"collaborate": ["finance", "analytics"], "budget": budget},
    )


async def wf_branding(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    lines = [
        "**Branding Strategy**",
        f"_Subject:_ {task[:140]}",
        "",
        "- **Essence** — 3 adjectives customers should feel",
        "- **Voice** — tone, words we use / avoid",
        "- **Visual system** — color, type, imagery rules (lightweight)",
        "- **Proof** — stories, testimonials, certifications",
        "- **Consistency checklist** — web, packaging, sales decks, social",
    ]
    return _result(
        "wf_marketing_branding",
        "Branding Strategy",
        "\n".join(lines),
        _steps("Essence", "System", "Proof"),
        {},
    )


async def wf_positioning(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    lines = [
        "**Market Positioning**",
        f"_Offer:_ {task[:140]}",
        "",
        "For **[beachhead customer]** who **[job/pain]**,",
        "**[brand]** is a **[category]** that **[key benefit]**.",
        "Unlike **[alternative]**, we **[differentiator + proof]**.",
        "",
        "Validate with 5 target customers: clarity, uniqueness, believability.",
    ]
    return _result(
        "wf_marketing_positioning",
        "Market Positioning",
        "\n".join(lines),
        _steps("Template", "Differentiator", "Validate"),
        {"collaborate": ["sales", "market_research"]},
    )


# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------


async def wf_sales_forecast(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    base = _num(task, 50.0)
    lines = [
        "**Sales Forecast (simple funnel)**",
        f"_Reference monthly deals/units:_ {base:,.0f}",
        "",
        f"| Stage | Rate | Volume |",
        f"|---|---:|---:|",
        f"| Leads | — | {base*10:,.0f} |",
        f"| Qualified (40%) | 40% | {base*4:,.0f} |",
        f"| Proposals (50%) | 50% | {base*2:,.0f} |",
        f"| Closed (50%) | 50% | {base:,.0f} |",
        "",
        "Adjust rates from CRM history; forecast low/base/high cases.",
    ]
    return _result(
        "wf_sales_forecast",
        "Sales Forecast",
        "\n".join(lines),
        _steps("Funnel", "Rates", "Cases"),
        {"collaborate": ["finance", "analytics"], "base_units": base},
    )


async def wf_pricing_analysis(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    opts = [
        DecisionOption(
            id="cost_plus",
            name="Cost-plus",
            scores={"margin": 0.7, "simplicity": 0.9, "market_fit": 0.45},
            risks=["Ignores WTP"],
        ),
        DecisionOption(
            id="value",
            name="Value-based",
            scores={"margin": 0.85, "simplicity": 0.4, "market_fit": 0.8},
            risks=["Needs research"],
        ),
        DecisionOption(
            id="penetration",
            name="Penetration",
            scores={"margin": 0.35, "simplicity": 0.7, "market_fit": 0.75},
            risks=["Hard to raise later"],
        ),
        DecisionOption(
            id="tiered",
            name="Good-better-best tiers",
            scores={"margin": 0.8, "simplicity": 0.55, "market_fit": 0.85},
            risks=["SKU sprawl"],
        ),
    ]
    req = DecisionRequest(
        question=task or "Which pricing approach?",
        criteria=[
            Criterion(id="margin", name="Margin", weight=0.4),
            Criterion(id="simplicity", name="Simplicity", weight=0.2),
            Criterion(id="market_fit", name="Market fit", weight=0.4),
        ],
        options=opts,
    )
    decision = await agent.decide(req)
    return _result(
        "wf_sales_pricing",
        "Pricing Analysis",
        decision.format() if decision else "",
        _steps("Options", "Score", "Recommend"),
        {"collaborate": ["finance", "marketing"]},
    )


async def wf_pipeline_review(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    lines = [
        "**Lead Pipeline Review**",
        "",
        "- **Hygiene:** next step + date on every open opp",
        "- **Stage definitions:** exit criteria documented",
        "- **Aging:** flag opps > 1.5× median stage time",
        "- **Concentration:** top-3 deals % of forecast",
        "- **Coverage:** pipeline / quota ≥ 3× for healthy months",
        "- **Actions:** revive, advance, or disqualify this week",
    ]
    return _result(
        "wf_sales_pipeline",
        "Lead Pipeline Review",
        "\n".join(lines),
        _steps("Hygiene", "Aging", "Coverage", "Actions"),
        {"collaborate": ["analytics"]},
    )


async def wf_customer_growth(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    lines = [
        "**Customer Growth Analysis**",
        "",
        "1. **Acquisition** — channel mix & CAC trend",
        "2. **Activation** — time-to-first-value",
        "3. **Retention** — cohort curves, churn reasons",
        "4. **Expansion** — upsell/cross-sell attach rate",
        "5. **Referral** — NPS / referral loop health",
        "",
        "Pick one bottleneck; run one experiment for 2 weeks.",
    ]
    return _result(
        "wf_sales_growth",
        "Customer Growth Analysis",
        "\n".join(lines),
        _steps("Funnel stages", "Bottleneck", "Experiment"),
        {"collaborate": ["marketing", "analytics"]},
    )


# ---------------------------------------------------------------------------
# Finance / Accounting (BI-side; complements FinanceAgent)
# ---------------------------------------------------------------------------


async def wf_bi_budget(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    income = _num(task, 10000.0)
    lines = [
        f"**Budget Creation** (reference inflow {income:,.2f})",
        "",
        f"- Revenue / inflow plan: {income:,.2f}",
        f"- COGS / direct (35%): {income*0.35:,.2f}",
        f"- OpEx (40%): {income*0.40:,.2f}",
        f"- Growth investment (15%): {income*0.15:,.2f}",
        f"- Reserve / profit (10%): {income*0.10:,.2f}",
        "",
        "Re-forecast monthly; variance review with owners.",
    ]
    return _result(
        "wf_bi_budget",
        "Budget Creation",
        "\n".join(lines),
        _steps("Inflow", "Allocate", "Owners"),
        {"collaborate": ["finance", "operations"], "income": income},
    )


async def wf_bi_cashflow(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", task.replace(",", ""))]
    inflow = nums[0] if nums else 8000.0
    outflow = nums[1] if len(nums) > 1 else inflow * 0.8
    net = inflow - outflow
    lines = [
        "**Cash Flow Forecast (monthly)**",
        f"- Inflows: {inflow:,.2f}",
        f"- Outflows: {outflow:,.2f}",
        f"- **Net:** {net:,.2f}",
        "",
        "Build 13-week rolling cash view for ops; stress −20% inflow case.",
    ]
    return _result(
        "wf_bi_cashflow",
        "Cash Flow Forecast",
        "\n".join(lines),
        _steps("In", "Out", "Net", "Stress"),
        {"collaborate": ["finance"], "net": net},
    )


async def wf_bi_loan_frame(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    principal = _num(task, 10000.0)
    lines = [
        "**Loan Comparison (BI framing)**",
        f"_Principal reference:_ {principal:,.2f}",
        "",
        "Evaluate offers on: APR, fees, term, prepayment, collateral, covenants.",
        "Prefer lower total cost of credit over teaser rates.",
        "",
        "_Detailed amortization is available via the Finance Agent collaboration._",
    ]
    return _result(
        "wf_bi_loan_comparison",
        "Loan Comparison",
        "\n".join(lines),
        _steps("Terms", "Criteria", "Next"),
        {"collaborate": ["finance"], "principal": principal},
    )


async def wf_profitability(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    rev = _num(task, 100000.0)
    lines = [
        "**Profitability Analysis**",
        f"_Reference revenue:_ {rev:,.2f}",
        "",
        f"| Metric | Estimate |",
        f"|---|---:|",
        f"| Gross margin (assumed 40%) | {rev*0.40:,.2f} |",
        f"| Contribution after variable | model per SKU |",
        f"| Operating margin target | 10–15% |",
        "",
        "Actions: raise price on inelastic SKUs, cut low-margin complexity, fix discount leakage.",
    ]
    return _result(
        "wf_bi_profitability",
        "Profitability Analysis",
        "\n".join(lines),
        _steps("Margins", "SKU view", "Actions"),
        {"collaborate": ["finance", "sales", "accounting"]},
    )


async def wf_journal_entries(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    amt = _num(task, 1000.0)
    lines = [
        "**Journal Entry Guidance**",
        f"_Context:_ {task[:140]}",
        f"_Example amount:_ {amt:,.2f}",
        "",
        "```",
        f"Dr  Expense / Asset ................ {amt:,.2f}",
        f"    Cr  Cash / Payable ............. {amt:,.2f}",
        "```",
        "",
        "Rules: every debit has a credit; document source; period-close checklist.",
        "_Not formal accounting advice — verify with your accountant._",
    ]
    return _result(
        "wf_accounting_journal",
        "Journal Entries",
        "\n".join(lines),
        _steps("Classify", "Entry", "Controls"),
        {"collaborate": ["finance"]},
    )


async def wf_financial_statements(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    lines = [
        "**Financial Statements Overview**",
        "",
        "- **P&L** — period performance (rev, COGS, opex, net income)",
        "- **Balance sheet** — assets = liabilities + equity snapshot",
        "- **Cash flow** — operating / investing / financing",
        "",
        "Read together: profit ≠ cash; check working capital and runway.",
    ]
    return _result(
        "wf_accounting_statements",
        "Financial Statements",
        "\n".join(lines),
        _steps("P&L", "BS", "CF"),
        {"collaborate": ["finance", "analytics"]},
    )


async def wf_ratio_analysis(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    lines = [
        "**Ratio Analysis**",
        "",
        "| Ratio | Formula | Healthy signal (general) |",
        "|---|---|---|",
        "| Current | CA / CL | > 1.2 |",
        "| Quick | (CA−inv) / CL | > 1.0 |",
        "| Gross margin | GM / Rev | industry-dependent |",
        "| Net margin | NI / Rev | positive & stable |",
        "| ROE | NI / Equity | exceeds cost of capital |",
        "| D/E | Debt / Equity | manageable serviceability |",
        "",
        "Trend > single snapshot; compare to peers.",
    ]
    calc = await agent.use_tool("calculator", expression="120000 / 100000")
    if calc and getattr(calc, "success", False):
        lines.append(f"_Example current ratio 120k/100k = {calc.output}_")
    return _result(
        "wf_accounting_ratios",
        "Ratio Analysis",
        "\n".join(lines),
        _steps("Liquidity", "Profitability", "Leverage"),
        {"collaborate": ["finance"]},
    )


async def wf_breakeven(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", task.replace(",", ""))]
    price = nums[0] if nums else 50.0
    variable = nums[1] if len(nums) > 1 else 20.0
    fixed = nums[2] if len(nums) > 2 else 10000.0
    cm = max(price - variable, 0.01)
    units = fixed / cm
    lines = [
        "**Break-even Analysis**",
        f"- Price: {price:,.2f}",
        f"- Variable cost / unit: {variable:,.2f}",
        f"- Contribution margin: {cm:,.2f}",
        f"- Fixed costs: {fixed:,.2f}",
        f"- **Break-even units:** {units:,.1f}",
        f"- **Break-even revenue:** {units * price:,.2f}",
    ]
    return _result(
        "wf_accounting_breakeven",
        "Break-even Analysis",
        "\n".join(lines),
        _steps("Inputs", "CM", "BE units"),
        {"be_units": units, "collaborate": ["finance", "sales"]},
    )


async def wf_cost_analysis(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    base = _num(task, 5000.0)
    lines = [
        "**Cost Analysis**",
        f"_Reference pool:_ {base:,.2f}",
        "",
        f"- Direct materials: {base*0.30:,.2f}",
        f"- Direct labor: {base*0.25:,.2f}",
        f"- Variable overhead: {base*0.15:,.2f}",
        f"- Fixed overhead allocation: {base*0.20:,.2f}",
        f"- Selling & admin: {base*0.10:,.2f}",
        "",
        "Next: ABC on high-variance buckets; target 10% cost-to-serve reduction.",
    ]
    return _result(
        "wf_accounting_cost",
        "Cost Analysis",
        "\n".join(lines),
        _steps("Classify", "Allocate", "Targets"),
        {"collaborate": ["operations", "finance"]},
    )


# ---------------------------------------------------------------------------
# Operations / HR / Projects
# ---------------------------------------------------------------------------


async def wf_process_optimization(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    lines = [
        "**Process Optimization**",
        f"_Process:_ {task[:140]}",
        "",
        "1. Map current state (steps, waits, handoffs, rework)",
        "2. Measure cycle time, defect rate, cost/step",
        "3. Identify bottleneck (Theory of Constraints)",
        "4. Remove waste (waiting, motion, overprocessing, defects)",
        "5. Pilot change; lock standard work; remeasure",
    ]
    return _result(
        "wf_ops_process",
        "Process Optimization",
        "\n".join(lines),
        _steps("Map", "Measure", "Improve", "Standardize"),
        {},
    )


async def wf_inventory(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    demand = _num(task, 100.0)
    lines = [
        "**Inventory Planning**",
        f"_Monthly demand ref:_ {demand:,.0f}",
        "",
        f"- Safety stock (2 weeks): ~{demand/2:,.0f}",
        f"- Reorder point heuristic: lead-time demand + safety",
        f"- Review ABC classes monthly; tighten A-item controls",
        "- Avoid overstock on C-items; watch expiry / obsolescence",
    ]
    return _result(
        "wf_ops_inventory",
        "Inventory Planning",
        "\n".join(lines),
        _steps("Demand", "Safety", "ROP"),
        {"collaborate": ["finance", "procurement"] if False else ["finance"]},
    )


async def wf_procurement(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    lines = [
        "**Procurement Planning**",
        "",
        "- Spec clarity before RFQ",
        "- ≥2–3 qualified suppliers for critical inputs",
        "- Total cost of ownership (not just unit price)",
        "- SLAs: quality, lead time, penalties",
        "- Dual-source high-risk SKUs",
    ]
    return _result(
        "wf_ops_procurement",
        "Procurement Planning",
        "\n".join(lines),
        _steps("Spec", "Source", "Contract"),
        {"collaborate": ["finance", "risk_compliance"]},
    )


async def wf_resource_allocation(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    lines = [
        "**Resource Allocation**",
        "",
        "1. List initiatives with expected value & effort",
        "2. Capacity calendar (people, machines, cash)",
        "3. Rank by value/effort under constraints",
        "4. Reserve 15–20% slack for interrupts",
        "5. Weekly reallocation stand-up",
    ]
    return _result(
        "wf_ops_resources",
        "Resource Allocation",
        "\n".join(lines),
        _steps("Demand", "Capacity", "Rank", "Slack"),
        {"collaborate": ["project_management", "hr", "finance"]},
    )


async def wf_hr_org(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    lines = [
        "**HR / Org Design Notes**",
        f"_Context:_ {task[:140]}",
        "",
        "- Role scorecards (outcomes, not activities)",
        "- Hiring plan tied to capacity bottlenecks",
        "- Onboarding 30/60/90",
        "- Performance: few KPIs + coaching cadence",
        "- Compliance: contracts, safety, local labor rules",
    ]
    return _result(
        "wf_hr_planning",
        "HR Planning",
        "\n".join(lines),
        _steps("Roles", "Hire", "Perform"),
        {"collaborate": ["operations", "finance", "risk_compliance"]},
    )


async def wf_project_plan(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    plan = await agent.plan(task, ctx)
    lines = [
        "**Project Planning**",
        f"_Project:_ {task[:140]}",
        "",
        plan or "",
        "",
        "**Controls:** RACI, RAID log, weekly status, change control.",
    ]
    return _result(
        "wf_pm_plan",
        "Project Planning",
        "\n".join(lines),
        _steps("Scope", "WBS", "Controls"),
        {"collaborate": ["operations", "finance"]},
    )


async def wf_scheduling(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    lines = [
        "**Scheduling**",
        "",
        "- Critical path first; protect with buffers",
        "- Level resources; avoid overallocation",
        "- Milestones every 1–2 weeks for visibility",
        "- Explicit dependencies; no hidden waits",
    ]
    return _result(
        "wf_pm_schedule",
        "Scheduling",
        "\n".join(lines),
        _steps("CPM", "Level", "Milestones"),
        {},
    )


async def wf_risk_tracking(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    lines = [
        "**Risk Tracking (RAID)**",
        "",
        "| ID | Risk | L | I | Score | Owner | Mitigation |",
        "|---|---|---:|---:|---:|---|---|",
        "| R1 | Scope creep | 3 | 4 | 12 | PM | Change board |",
        "| R2 | Key person | 2 | 5 | 10 | Lead | Cross-train |",
        "| R3 | Vendor delay | 3 | 3 | 9 | Ops | Dual source |",
        "",
        "Review weekly; escalate score ≥ 12.",
    ]
    return _result(
        "wf_pm_risk",
        "Risk Tracking",
        "\n".join(lines),
        _steps("Log", "Score", "Mitigate"),
        {"collaborate": ["risk_compliance"]},
    )


async def wf_milestones(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    lines = [
        "**Milestone Monitoring**",
        "",
        "- Green: on track · Amber: ≤10% slip · Red: path broken",
        "- Each milestone has evidence of done",
        "- Slip triggers re-plan within 48h",
        "- Stakeholder update template: status, blockers, ask",
    ]
    return _result(
        "wf_pm_milestones",
        "Milestone Monitoring",
        "\n".join(lines),
        _steps("Status", "Evidence", "Comms"),
        {},
    )


# ---------------------------------------------------------------------------
# Analytics / Research / Risk / Strategy
# ---------------------------------------------------------------------------


async def wf_kpi_dashboard(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    lines = [
        "**KPI Dashboard Blueprint**",
        "",
        "| Layer | Examples | Cadence |",
        "|---|---|---|",
        "| North star | Weekly active paying / margin $ | Weekly |",
        "| Growth | Leads, conversion, CAC | Weekly |",
        "| Revenue | MRR/GMV, AOV | Weekly |",
        "| Ops | On-time %, defect % | Daily/weekly |",
        "| Finance | Cash, burn, runway | Weekly |",
        "",
        "Max 7–9 visible KPIs; deep-dives on demand.",
    ]
    facts = _facts(ctx, "kpi", "metric", "revenue")
    if facts:
        lines += ["", "**Graph KPIs/metrics:**"] + [f"- {f}" for f in facts]
    return _result(
        "wf_analytics_kpi",
        "KPI Dashboard",
        "\n".join(lines),
        _steps("North star", "Layers", "Cadence"),
        {"collaborate": ["finance", "sales", "operations"]},
    )


async def wf_trend_analysis(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    lines = [
        "**Trend Analysis**",
        f"_Series:_ {task[:140]}",
        "",
        "1. Plot level, seasonality, outliers",
        "2. YoY and MoM changes",
        "3. Segment breakdown (channel, product, region)",
        "4. Hypothesize drivers; test with one controlled change",
        "5. Document narrative for stakeholders",
    ]
    return _result(
        "wf_analytics_trend",
        "Trend Analysis",
        "\n".join(lines),
        _steps("Visualize", "Decompose", "Narrate"),
        {},
    )


async def wf_performance_report(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    lines = [
        "**Performance Report Template**",
        f"_Period focus:_ {task[:120]}",
        "",
        "1. Executive summary (5 lines)",
        "2. KPI table vs target / prior",
        "3. Wins & misses with owners",
        "4. Risks & decisions needed",
        "5. Next-period priorities (max 3)",
    ]
    return _result(
        "wf_analytics_report",
        "Performance Reports",
        "\n".join(lines),
        _steps("Summary", "KPIs", "Actions"),
        {"collaborate": ["strategy"]},
    )


async def wf_forecasting(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    lines = [
        "**Forecasting Approach**",
        "",
        "- Baseline: trailing average or seasonal naive",
        "- Drivers: pipeline, capacity, seasonality, price",
        "- Scenarios: base / upside (+15%) / downside (−20%)",
        "- Accuracy tracking: MAPE; recalibrate monthly",
    ]
    return _result(
        "wf_analytics_forecast",
        "Forecasting",
        "\n".join(lines),
        _steps("Baseline", "Drivers", "Scenarios"),
        {"collaborate": ["finance", "sales"]},
    )


async def wf_market_research(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    lines = [
        "**Market Research Brief**",
        f"_Question:_ {task[:140]}",
        "",
        "1. Define decision this research will change",
        "2. Secondary research (reports, competitors, public data)",
        "3. Primary: 10–20 interviews / survey",
        "4. Synthesis: jobs, alternatives, willingness to pay",
        "5. Implications → product, pricing, GTM",
    ]
    return _result(
        "wf_research_market",
        "Market Research",
        "\n".join(lines),
        _steps("Question", "Secondary", "Primary", "Implications"),
        {"collaborate": ["marketing", "strategy"]},
    )


async def wf_swot(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    farm = any(w in task.lower() for w in ("farm", "crop", "agriculture", "produce"))
    s = ["Core capability", "Customer access", "Brand trust"]
    w = ["Limited capital", "Process gaps", "Talent depth"]
    o = ["Adjacent segments", "Partnerships", "Digital channels"]
    t = ["Competition", "Cost inflation", "Regulation"]
    if farm:
        s.append("Land / production base")
        o.append("Farm-to-table / premium")
        t.append("Weather & disease")
    lines = [
        f"**SWOT** — {task[:120]}",
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
        "**Moves:** SO bets, WT mitigations, time-boxed weakness fix.",
    ]
    data: dict[str, Any] = {"collaborate": ["strategy", "finance"]}
    if farm:
        data["collaborate"] = ["agriculture", "finance", "strategy"]
    return _result(
        "wf_risk_swot",
        "SWOT Analysis",
        "\n".join(lines),
        _steps("S", "W", "O", "T", "Moves"),
        data,
    )


async def wf_risk_assessment(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    lines = [
        "**Risk Assessment**",
        f"_Scope:_ {task[:140]}",
        "",
        "| Category | Example | L | I | Response |",
        "|---|---|---:|---:|---|",
        "| Strategic | Wrong market | 2 | 5 | Validate faster |",
        "| Financial | Cash shortfall | 3 | 5 | Buffer + forecast |",
        "| Operational | Key process fail | 3 | 4 | Redundancy |",
        "| Compliance | Regulatory miss | 2 | 5 | Checklist + counsel |",
        "| Cyber/data | Breach | 2 | 5 | Controls + backup |",
        "",
        "Score = L×I; own every score ≥ 12.",
    ]
    return _result(
        "wf_risk_assessment",
        "Risk Assessment",
        "\n".join(lines),
        _steps("Identify", "Score", "Respond"),
        {"collaborate": ["finance", "operations"]},
    )


async def wf_compliance(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    lines = [
        "**Compliance Review Checklist**",
        "",
        "- [ ] Business registration & licenses current",
        "- [ ] Tax filings calendar owned",
        "- [ ] Employment contracts & labor law",
        "- [ ] Data privacy / customer consent",
        "- [ ] Health & safety (if applicable)",
        "- [ ] Industry-specific permits",
        "- [ ] Insurance coverage reviewed annually",
        "",
        "_Not legal advice — engage qualified counsel for jurisdiction-specific rules._",
    ]
    return _result(
        "wf_risk_compliance",
        "Compliance Review",
        "\n".join(lines),
        _steps("Register", "Tax", "Labor", "Data", "Safety"),
        {},
    )


async def wf_decision_support(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    opts = [
        DecisionOption(
            id="a",
            name="Act now",
            scores={"value": 0.8, "speed": 0.9, "risk": 0.6},
            risks=["Incomplete info"],
        ),
        DecisionOption(
            id="b",
            name="Pilot first (time-boxed)",
            scores={"value": 0.7, "speed": 0.5, "risk": 0.3},
            risks=["Delay cost"],
        ),
        DecisionOption(
            id="c",
            name="Defer / monitor",
            scores={"value": 0.3, "speed": 0.2, "risk": 0.2},
            risks=["Missed window"],
        ),
    ]
    req = DecisionRequest(
        question=task or "What should we do?",
        criteria=[
            Criterion(id="value", name="Expected value", weight=0.45),
            Criterion(id="speed", name="Speed to impact", weight=0.25),
            Criterion(id="risk", name="Risk", weight=0.3, maximize=False),
        ],
        options=opts,
    )
    decision = await agent.decide(req)
    body = decision.format() if decision else ""
    # Explainability envelope
    lines = [
        body,
        "",
        "**Evidence used:**",
        f"- Memories: {len(ctx.get('memories') or [])}",
        f"- Graph facts: {len(ctx.get('graph_facts') or [])}",
        f"- Documents: {len(ctx.get('documents') or [])}",
    ]
    for f in (ctx.get("graph_facts") or [])[:4]:
        lines.append(f"  - {f}")
    return _result(
        "wf_risk_decision_support",
        "Decision Support",
        "\n".join(lines),
        _steps("Frame", "Score", "Explain"),
        {"collaborate": ["strategy", "finance"]},
    )


async def wf_strategy_options(agent: Any, ctx: dict[str, Any], params: dict[str, Any]) -> WorkflowResult:
    task = _task(params, ctx)
    opts = [
        DecisionOption(
            id="focus",
            name="Deepen core (focus)",
            scores={"fit": 0.9, "upside": 0.6, "risk": 0.3},
            risks=["Missed adjacency"],
        ),
        DecisionOption(
            id="expand",
            name="Expand adjacency",
            scores={"fit": 0.6, "upside": 0.85, "risk": 0.55},
            risks=["Dilution", "Execution load"],
        ),
        DecisionOption(
            id="transform",
            name="Transform model",
            scores={"fit": 0.4, "upside": 0.95, "risk": 0.8},
            risks=["High uncertainty"],
        ),
    ]
    req = DecisionRequest(
        question=task or "Strategic direction?",
        criteria=[
            Criterion(id="fit", name="Capability fit", weight=0.35),
            Criterion(id="upside", name="Upside", weight=0.35),
            Criterion(id="risk", name="Risk", weight=0.3, maximize=False),
        ],
        options=opts,
    )
    decision = await agent.decide(req)
    return _result(
        "wf_strategy_direction",
        "Strategic Direction",
        decision.format() if decision else "",
        _steps("Options", "Score", "Recommend"),
        {"collaborate": ["finance", "risk_compliance", "market_research"]},
    )


def register_all_bi_workflows(
    library: Any,
    agent: Any,
    *,
    domain: str,
    workflow_ids: list[str],
) -> None:
    """Register selected workflows onto an advisor's library."""
    catalog: dict[str, tuple[str, str, list[str], list[str], Handler]] = {
        # id_suffix -> (name, description, triggers, step_titles, handler)
        "create_plan": (
            "Create Business Plan",
            "Lean business plan canvas and steps",
            ["business plan", "create business plan", "write a business plan"],
            ["Context", "Canvas", "Plan", "Evidence"],
            wf_business_plan,
        ),
        "startup_planning": (
            "Startup Planning",
            "Validate-build-traction startup path",
            ["startup", "new venture", "launch a business"],
            ["Validate", "Build", "Traction", "Capital"],
            wf_startup_planning,
        ),
        "expansion_planning": (
            "Expansion Planning",
            "Geo/segment/product expansion plan",
            ["expand", "expansion", "new market entry", "scale the business"],
            ["Target", "Mode", "Resources", "Pilot"],
            wf_expansion_planning,
        ),
        "business_model": (
            "Business Model Analysis",
            "Compare business model options",
            ["business model", "revenue model", "monetization"],
            ["Options", "Score", "Recommend"],
            wf_business_model,
        ),
        "feasibility": (
            "Feasibility Study",
            "Multi-lens feasibility go/no-go",
            ["feasibility", "is it feasible", "should we start"],
            ["Lenses", "Signals", "Recommendation"],
            wf_feasibility,
        ),
        "marketing_plan": (
            "Marketing Plan",
            "Audience, positioning, channels, KPIs",
            ["marketing plan", "go to market marketing", "promotion plan"],
            ["Audience", "Positioning", "Channels", "KPIs"],
            wf_marketing_plan,
        ),
        "segmentation": (
            "Customer Segmentation",
            "Segment and prioritize customers",
            ["segmentation", "customer segments", "target audience"],
            ["Axes", "Segments", "Priority"],
            wf_segmentation,
        ),
        "campaign": (
            "Campaign Planning",
            "Campaign budget and KPI plan",
            ["campaign", "ad campaign", "launch campaign"],
            ["Budget", "Creative", "KPIs"],
            wf_campaign,
        ),
        "branding": (
            "Branding Strategy",
            "Brand essence, voice, system",
            ["branding", "brand strategy", "rebrand"],
            ["Essence", "System", "Proof"],
            wf_branding,
        ),
        "positioning": (
            "Market Positioning",
            "Positioning statement and validation",
            ["positioning", "market position", "differentiate"],
            ["Template", "Differentiator", "Validate"],
            wf_positioning,
        ),
        "sales_forecast": (
            "Sales Forecast",
            "Funnel-based sales forecast",
            ["sales forecast", "forecast sales", "pipeline forecast"],
            ["Funnel", "Rates", "Cases"],
            wf_sales_forecast,
        ),
        "pricing": (
            "Pricing Analysis",
            "Multi-criteria pricing strategy",
            ["pricing", "price point", "how much to charge"],
            ["Options", "Score", "Recommend"],
            wf_pricing_analysis,
        ),
        "pipeline": (
            "Lead Pipeline Review",
            "CRM pipeline hygiene and coverage",
            ["pipeline", "sales pipeline", "lead pipeline"],
            ["Hygiene", "Aging", "Coverage", "Actions"],
            wf_pipeline_review,
        ),
        "customer_growth": (
            "Customer Growth Analysis",
            "Acquisition to referral growth lens",
            ["customer growth", "grow customers", "retention growth"],
            ["Funnel", "Bottleneck", "Experiment"],
            wf_customer_growth,
        ),
        "budget": (
            "Budget Creation",
            "Business budget allocation",
            ["create budget", "business budget", "annual budget"],
            ["Inflow", "Allocate", "Owners"],
            wf_bi_budget,
        ),
        "cashflow": (
            "Cash Flow Forecast",
            "Monthly cash flow outlook",
            ["cash flow forecast", "cashflow forecast", "liquidity forecast"],
            ["In", "Out", "Net", "Stress"],
            wf_bi_cashflow,
        ),
        "profitability": (
            "Profitability Analysis",
            "Margin and profitability drivers",
            ["profitability", "profit analysis", "margin analysis"],
            ["Margins", "SKU", "Actions"],
            wf_profitability,
        ),
        "journal": (
            "Journal Entries",
            "Double-entry journal guidance",
            ["journal entry", "bookkeeping entry", "debit credit"],
            ["Classify", "Entry", "Controls"],
            wf_journal_entries,
        ),
        "statements": (
            "Financial Statements",
            "P&L, BS, CF overview",
            ["financial statements", "balance sheet", "income statement", "p&l"],
            ["P&L", "BS", "CF"],
            wf_financial_statements,
        ),
        "ratios": (
            "Ratio Analysis",
            "Key financial ratios",
            ["ratio analysis", "financial ratios", "current ratio"],
            ["Liquidity", "Profitability", "Leverage"],
            wf_ratio_analysis,
        ),
        "breakeven": (
            "Break-even Analysis",
            "Break-even units and revenue",
            ["break-even", "breakeven", "break even"],
            ["Inputs", "CM", "BE"],
            wf_breakeven,
        ),
        "cost_analysis": (
            "Cost Analysis",
            "Cost structure breakdown",
            ["cost analysis", "cost structure", "cost to serve"],
            ["Classify", "Allocate", "Targets"],
            wf_cost_analysis,
        ),
        "process": (
            "Process Optimization",
            "Map-measure-improve process",
            ["process optimization", "improve process", "lean process"],
            ["Map", "Measure", "Improve", "Standardize"],
            wf_process_optimization,
        ),
        "inventory": (
            "Inventory Planning",
            "Safety stock and reorder heuristics",
            ["inventory", "stock planning", "reorder"],
            ["Demand", "Safety", "ROP"],
            wf_inventory,
        ),
        "procurement": (
            "Procurement Planning",
            "Sourcing and supplier plan",
            ["procurement", "purchasing plan", "supplier"],
            ["Spec", "Source", "Contract"],
            wf_procurement,
        ),
        "resources": (
            "Resource Allocation",
            "Allocate scarce resources",
            ["resource allocation", "allocate resources", "capacity plan"],
            ["Demand", "Capacity", "Rank", "Slack"],
            wf_resource_allocation,
        ),
        "hr_planning": (
            "HR Planning",
            "Roles, hiring, performance",
            ["hr plan", "hiring plan", "org design", "headcount"],
            ["Roles", "Hire", "Perform"],
            wf_hr_org,
        ),
        "project_plan": (
            "Project Planning",
            "Project WBS and controls",
            ["project plan", "project planning", "plan the project"],
            ["Scope", "WBS", "Controls"],
            wf_project_plan,
        ),
        "scheduling": (
            "Scheduling",
            "Critical path and leveling",
            ["project schedule", "scheduling", "gantt"],
            ["CPM", "Level", "Milestones"],
            wf_scheduling,
        ),
        "risk_tracking": (
            "Risk Tracking",
            "RAID risk log",
            ["risk tracking", "raid log", "project risks"],
            ["Log", "Score", "Mitigate"],
            wf_risk_tracking,
        ),
        "milestones": (
            "Milestone Monitoring",
            "Milestone health checks",
            ["milestone", "milestones", "project status"],
            ["Status", "Evidence", "Comms"],
            wf_milestones,
        ),
        "kpi_dashboard": (
            "KPI Dashboard",
            "KPI layers and cadence",
            ["kpi dashboard", "kpi", "metrics dashboard"],
            ["North star", "Layers", "Cadence"],
            wf_kpi_dashboard,
        ),
        "trend": (
            "Trend Analysis",
            "Decompose and narrate trends",
            ["trend analysis", "trends", "yo y"],
            ["Visualize", "Decompose", "Narrate"],
            wf_trend_analysis,
        ),
        "performance_report": (
            "Performance Reports",
            "Stakeholder performance report",
            ["performance report", "business report", "monthly report"],
            ["Summary", "KPIs", "Actions"],
            wf_performance_report,
        ),
        "forecasting": (
            "Forecasting",
            "Scenario forecasting approach",
            ["forecasting", "business forecast", "demand forecast"],
            ["Baseline", "Drivers", "Scenarios"],
            wf_forecasting,
        ),
        "market_research": (
            "Market Research",
            "Research brief and method",
            ["market research", "customer research", "competitor research"],
            ["Question", "Secondary", "Primary", "Implications"],
            wf_market_research,
        ),
        "swot": (
            "SWOT Analysis",
            "Strengths weaknesses opportunities threats",
            ["swot", "strengths weaknesses"],
            ["S", "W", "O", "T", "Moves"],
            wf_swot,
        ),
        "risk_assessment": (
            "Risk Assessment",
            "Enterprise risk matrix",
            ["risk assessment", "assess risks", "enterprise risk"],
            ["Identify", "Score", "Respond"],
            wf_risk_assessment,
        ),
        "compliance": (
            "Compliance Review",
            "Compliance checklist",
            ["compliance", "regulatory review", "license check"],
            ["Register", "Tax", "Labor", "Data", "Safety"],
            wf_compliance,
        ),
        "decision_support": (
            "Decision Support",
            "MCDA decision support with evidence",
            ["decision support", "help me decide", "what should we do"],
            ["Frame", "Score", "Explain"],
            wf_decision_support,
        ),
        "strategy_direction": (
            "Strategic Direction",
            "Focus vs expand vs transform",
            ["strategic direction", "strategy options", "corporate strategy"],
            ["Options", "Score", "Recommend"],
            wf_strategy_options,
        ),
        "loan_comparison": (
            "Loan Comparison",
            "Loan framing; deep calc collaborates with Finance Agent",
            ["loan comparison", "compare loans", "financing options"],
            ["Terms", "Collaborate", "Recommend"],
            wf_bi_loan_frame,
        ),
        "investment": (
            "Investment Analysis",
            "Capital allocation framing",
            ["investment analysis", "where to invest capital"],
            ["Options", "Risk/return", "Recommend"],
            wf_strategy_options,
        ),
    }

    for wid in workflow_ids:
        if wid not in catalog:
            continue
        name, desc, triggers, step_titles, handler = catalog[wid]
        wf_id = new_workflow_id(domain, wid)

        async def _bound(
            c: dict[str, Any],
            p: dict[str, Any],
            _h: Handler = handler,
            _a: Any = agent,
        ) -> Any:
            return await _h(_a, c, p)

        library.register(
            Workflow(
                id=wf_id,
                name=name,
                domain=domain,
                description=desc,
                triggers=triggers,
                steps=[
                    WorkflowStep(id=f"s{i+1}", title=t) for i, t in enumerate(step_titles)
                ],
                handler=_bound,
            )
        )

# SAGE v0.3.1 — Business Intelligence Suite

**Status:** Implemented  
**Builds on:** v0.3.0 Domain Intelligence  
**Compatibility:** Backward compatible — `BusinessAgent` import still resolves to the BI hub advisor

---

## Goal

Elevate **Business** from a single strategy agent to a first-class domain ecosystem equal in depth to Agriculture:

```
Business Intelligence Suite
├── Business Advisor          (hub / planning)
├── Marketing Advisor
├── Sales Advisor
├── Operations Advisor
├── Financial Planning Advisor
├── Accounting Advisor
├── HR Advisor
├── Project Management Advisor
├── Market Research Advisor
├── Business Analytics Advisor
├── Risk & Compliance Advisor
└── Strategy Advisor
```

---

## Folder structure

```
sage/agents/domain/business/
├── __init__.py          # Public exports + BusinessAgent alias
├── base.py              # BusinessAdvisor base + bi_profile()
├── advisors.py          # 12 specialized advisors
├── workflows.py         # Shared BI workflow library (~40 workflows)
└── suite.py             # Factory + BusinessIntelligenceSuite

sage/knowledge/graph/
├── business_seed.py     # BI ontology text + lexicon
├── models.py            # Extended EntityType / RelationType
└── extract.py           # Business relation patterns + lexicon merge
```

---

## Architecture

Each advisor uses the same internal architecture as Agriculture (`DomainAgent`):

```
Capability Profile
Workflow Library
Knowledge Graph Interface
Memory Interface
Decision Engine Interface
Reasoning Strategy Selector
Planner Interface
Tool Manager
Response Generator
Cross-agent collaboration (depth-limited)
```

### Registration

`AgentModule` (v0.3.1) loads:

1. Core agents (general, research, planning, document)
2. Agriculture, Finance, Programming
3. **All 12 BI advisors** via `create_business_advisors()`

Workflows merge into the shared `WorkflowLibrary` DI service.

---

## Knowledge Graph extensions

### New entity types
`company`, `customer`, `supplier`, `service`, `employee`, `department`, `market`, `competitor`, `campaign`, `revenue`, `expense`, `asset`, `liability`, `kpi`, `project`, `goal`, `risk`, `opportunity`

### New relations
`sells_to`, `buys_from`, `employs`, `reports_to`, `competes_with`, `targets`, `measures`, `funds`, `manages`, `belongs_to`, `generates`, `incurs`, `mitigates`, `serves`

### Seed ontology
Boot merges `BUSINESS_SEED_ONTOLOGY` after the agriculture core seed (source=`business_seed_ontology`).

Existing graph features unchanged: confidence, provenance, version history, bidirectional edges, path traversal, semantic search via retrieval.

---

## Workflow catalog (selected)

| Area | Workflows |
|---|---|
| Planning | Create Business Plan, Startup, Expansion, Business Model, Feasibility |
| Marketing | Marketing Plan, Segmentation, Campaign, Branding, Positioning |
| Sales | Sales Forecast, Pricing Analysis, Pipeline Review, Customer Growth |
| Finance (BI) | Budget, Cash Flow Forecast, Profitability, Loan/Investment framing |
| Accounting | Journal Entries, Financial Statements, Ratios, Break-even, Cost Analysis |
| Operations | Process Optimization, Inventory, Procurement, Resource Allocation |
| Projects | Project Plan, Scheduling, Risk Tracking, Milestones |
| Analytics | KPI Dashboard, Trends, Performance Reports, Forecasting |
| Research | Market Research |
| Risk | SWOT, Risk Assessment, Compliance Review, Decision Support |
| Strategy | Strategic Direction |

---

## Cross-agent collaboration

```
User → Orchestrator → Agriculture Agent
                         ↓ cost?
                      Finance / Financial Planning
                         ↓
                   Unified response

User → Marketing Advisor
           ↓
        Analytics + Sales
           ↓
     Decision Engine scoring
```

- Orchestrator domain routing extended for BI keywords
- Collaboration depth limit unchanged (`collab_depth >= 1` stops fan-out)
- Advisors declare suite-wide `collaborate_with` lists

---

## Capability Registry

- `business_agent` principal retained as **alias** of hub (metadata `alias_of=business_advisor`)
- Each advisor registered with `metadata.suite = "business_intelligence"`
- Dispatch scoring via existing capability registry boosts

---

## Explainability

Workflow outputs that use the Decision Engine include ranking, trade-offs, confidence, and method notes.  
`decision_support` workflow adds memory/graph/document evidence counts.

---

## Learning

Learning engine domain patterns extended for marketing, sales, operations, accounting, strategy, analytics, and common BI workflow phrases.

---

## Migration notes

| Change | Impact |
|---|---|
| `from sage.agents.domain.business import BusinessAgent` | Still works → hub advisor |
| Single business agent in agent list | Replaced by 12 advisors; hub keeps `domain=business` |
| Capability `business_agent` | Still registered (alias) |
| KG schema | No migration — new enum values are strings in existing columns |
| Version | Package `0.3.1` |

No breaking public API changes required for Orchestrator, Decision Engine, or Memory.

---

## Tests

See `tests/unit/test_business_intelligence.py`.

---

## Next

v0.4.0 Automation — external tools, autonomous multi-step jobs, marketplace hooks.

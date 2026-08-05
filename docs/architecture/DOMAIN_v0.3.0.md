# SAGE v0.3.0 — Domain Intelligence

**Status:** Implemented  
**Builds on:** v0.2.0 Intelligence Layer

---

## Goal

Turn capability *declarations* into living domain specialists that:

- Share one internal architecture
- Run reusable **workflows**
- Use the **Knowledge Graph**, **Retrieval**, **Reasoning**, **Planning**, and **Decision Engine**
- **Collaborate** across domains under Orchestrator coordination

---

## Consistent Agent Architecture

```
Agent
├── Capability Profile
├── Domain Knowledge (KG + seeds)
├── Reasoning Strategy Selector
├── Workflow Library
├── Tool Manager
├── Memory Interface
├── Knowledge Graph Interface
├── Planner
├── Decision Engine
└── Response Generator
```

Implemented as `DomainAgent` (`sage.agents.domain_base`).

---

## Decision Engine (v0.3.5-class, shipped in 0.3.0)

`sage.decision` — shared multi-criteria decision analysis:

- Weighted criteria with min-max normalization
- Minimize/maximize per criterion
- Risk penalties
- Trade-off narration
- Confidence from score separation + matrix completeness

Used by Agriculture (method compare), Finance (loans/investments), Business (pricing).

---

## Workflow Library

`sage.agents.workflows` — action-oriented recipes registered per agent and merged into a shared `WorkflowLibrary` in DI.

### Agriculture
- Diagnose Crop Disease
- Create Irrigation Plan
- Estimate Fertilizer Needs
- Generate Crop Calendar
- Compare Farming Methods

### Finance & Accounting
- Loan Comparison
- Budget Creation
- Investment Analysis
- Cash Flow Projection
- Expense Forecast

### Business Strategy
- SWOT Analysis
- Business Planning
- Pricing Strategy
- KPI Monitoring Setup
- Go-to-Market

### Programming
- Code Scaffold
- Debug Assist
- Refactor Plan
- Test Generation Plan
- SAGE Plugin Scaffold
- Architecture Review

---

## Cross-Agent Collaboration

```
User → Orchestrator → Agriculture Agent
                         ↓ (needs cost)
                      Finance Agent
                         ↓
                   Unified response
```

- Depth-limited (`collab_depth`) to prevent recursion
- Workflows may set `data.collaborate = ["finance", …]`
- Nested collab sections stripped from child outputs

---

## Domain Agents (priority order)

| Agent | Principal | Status |
|---|---|---|
| Agriculture | `agriculture_agent` | ⭐ Active |
| Finance & Accounting | `finance_agent` | Active |
| Business Strategy | `business_agent` | Active |
| Programming | `programming_agent` | Active |

Plus existing core agents: general, research, planning, document.

---

## Boot

`decision` module registers before `agents`.  
Capability Registry entries marked `status: active` with workflow lists.

---

## Next

**v0.4.0 Automation** — advanced tools, multi-step autonomous workflows, plugin marketplace hooks, richer weather/API integrations for agriculture.

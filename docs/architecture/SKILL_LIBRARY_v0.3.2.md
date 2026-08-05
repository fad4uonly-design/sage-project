# SAGE v0.3.2 — Shared Skill Library

**Status:** Implemented  
**Purpose:** Bridge between domain suites (v0.3.x) and automation (v0.4.0)

---

## Why

Domain agents previously owned overlapping workflows (SWOT, planning, KPIs, decisions).  
The **Skill Library** extracts cross-cutting capabilities into a shared, DI-registered subsystem so agents **orchestrate skills** instead of duplicating logic.

This is the recommended pre-automation foundation for:

- Workflow Engine (compose skills into stateful runs)
- Tool Framework (skills call tools under permissions)
- Audit / approval (skill invocations are discrete, loggable units)

---

## Architecture

```
Skill Library
├── Analysis Skills
│   ├── SWOT
│   ├── Risk Assessment
│   └── KPI Analysis
├── Planning Skills
│   ├── Project Planning
│   ├── Budget Planning
│   └── Crop Planning
├── Reporting Skills
│   ├── Report Outline
│   ├── Dashboard Outline
│   └── Executive Summary
├── Communication Skills
│   ├── Email Drafting
│   ├── Meeting Notes
│   └── Presentation Brief
└── Decision Skills
    ├── Weighted Comparison   → Decision Engine
    ├── Trade-off Analysis
    └── Recommendations
```

```
User → Orchestrator → Domain Agent
                         ├─ domain Workflow (specific)
                         ├─ Skill Library (shared)   ← NEW
                         └─ reason / plan fallback
```

---

## Package layout

```
sage/skills/
├── __init__.py
├── models.py          # SkillManifest, SkillRequest, SkillResult, SkillCategory
├── interfaces.py      # Skill, SkillLibrary protocols
├── base.py            # BaseSkill helper
├── library.py         # DefaultSkillLibrary
├── service.py         # SkillsModule (boot)
└── builtin/
    ├── __init__.py    # register_builtin_skills()
    ├── analysis.py
    ├── planning.py
    ├── reporting.py
    ├── communication.py
    └── decision.py
```

---

## Interfaces

```python
class Skill(Protocol):
    manifest: SkillManifest
    def match_score(self, text: str, *, domain: str | None = None) -> float: ...
    async def execute(self, request: SkillRequest) -> SkillResult: ...

class SkillLibrary(Protocol):
    def register(self, skill: Skill) -> None: ...
    def match(self, text, *, domain=None, category=None, limit=5) -> list[tuple[Skill, float]]: ...
    async def invoke(self, skill_id, *, task="", params=None, context=None, principal="core") -> SkillResult: ...
    async def invoke_best(self, task, *, domain=None, min_score=0.25, ...) -> SkillResult | None: ...
```

---

## Agent integration

`DomainAgent` now:

1. Tries **domain workflows** (unchanged, highest priority)
2. Else **`use_best_skill()`** via Skill Library
3. Else reason/plan default path

Helpers:

- `agent.use_skill(skill_id, task=...)`
- `agent.use_best_skill(task, context=...)`

Context injects `_plan_fn` / `_decide_fn` so skills can use Planning + Decision engines without circular imports.

---

## Permissions

Skills may declare `manifest.permissions`.  
`DefaultSkillLibrary.invoke` calls `PermissionManager.require(principal, perm)` when present.

---

## Boot order

```
… → decision → tools → skills → capabilities → agents → …
```

---

## Long-term suites (unchanged vision)

| Suite | Status |
|---|---|
| Agriculture Intelligence | ✅ |
| Business Intelligence | ✅ (v0.3.1) |
| Finance Intelligence | ✅ (Finance Agent + BI FP&A/Accounting) |
| Programming Intelligence | ✅ |
| Research Intelligence | 🔜 (can consume analysis/research skills) |

All share Memory, KG, Reasoning, Decision, **Skills**, Orchestrator.

---

## Path to v0.4.0 Automation

| Component | Builds on |
|---|---|
| Workflow Engine | Skills as atomic steps |
| Tool Framework | Skills + Permission Manager |
| Automation Manager | Scheduler + skill/workflow invoke |
| Plugin Runtime | Register custom skills |
| Execution Audit | Log each `skills.invoked` |
| Human Approval | Gate skills with dangerous permissions |

---

## Compatibility

- No breaking API changes
- Domain workflows still win when they match strongly
- Version: **0.3.2**

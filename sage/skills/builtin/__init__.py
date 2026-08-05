"""Register all built-in shared skills."""

from __future__ import annotations

from typing import Any

from sage.skills.builtin.analysis import (
    KPIAnalysisSkill,
    RiskAssessmentSkill,
    SWOTSkill,
)
from sage.skills.builtin.communication import (
    EmailDraftSkill,
    ExecutiveBriefSkill,
    MeetingNotesSkill,
)
from sage.skills.builtin.decision import (
    RecommendationSkill,
    TradeoffAnalysisSkill,
    WeightedComparisonSkill,
)
from sage.skills.builtin.planning import (
    BudgetPlanningSkill,
    CropPlanningSkill,
    ProjectPlanningSkill,
)
from sage.skills.builtin.reporting import (
    DashboardOutlineSkill,
    ExecutiveSummarySkill,
    ReportOutlineSkill,
)
from sage.skills.interfaces import Skill
from sage.skills.library import DefaultSkillLibrary


def all_builtin_skills() -> list[Skill]:
    return [
        # Analysis
        SWOTSkill(),
        RiskAssessmentSkill(),
        KPIAnalysisSkill(),
        # Planning
        ProjectPlanningSkill(),
        BudgetPlanningSkill(),
        CropPlanningSkill(),
        # Reporting
        ReportOutlineSkill(),
        DashboardOutlineSkill(),
        ExecutiveSummarySkill(),
        # Communication
        EmailDraftSkill(),
        MeetingNotesSkill(),
        ExecutiveBriefSkill(),
        # Decision
        WeightedComparisonSkill(),
        TradeoffAnalysisSkill(),
        RecommendationSkill(),
    ]


def register_builtin_skills(library: DefaultSkillLibrary) -> int:
    skills = all_builtin_skills()
    for s in skills:
        library.register(s)
    return len(skills)

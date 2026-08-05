"""Built-in workflow definitions for v0.4.0."""

from __future__ import annotations

from sage.workflow.models import StepType, WorkflowDefinition, WorkflowStepDef


def business_expansion_report() -> WorkflowDefinition:
    """
    Prepare business expansion report:
    research-ish set → market skill → finance agent → risk → decision → exec summary → memory
    """
    return WorkflowDefinition(
        id="wfdef_business_expansion_report",
        name="business_expansion_report",
        version="1.0.0",
        description="Multi-step expansion report using skills, agents, and decision engine",
        entry="set_task",
        tags=["business", "report", "automation"],
        steps=[
            WorkflowStepDef(
                id="set_task",
                type=StepType.SET,
                name="Initialize",
                params={
                    "task": "{{task}}",
                    "topic": "{{task}}",
                },
                next="market",
            ),
            WorkflowStepDef(
                id="market",
                type=StepType.SKILL,
                name="Market framing",
                skill_id="skill_analysis_swot",
                params={"task": "{{task}}"},
                input_key="market_swot",
                next="finance",
            ),
            WorkflowStepDef(
                id="finance",
                type=StepType.AGENT,
                name="Finance input",
                agent_domain="finance",
                params={"task": "Expense forecast and budget notes for: {{task}}"},
                input_key="finance",
                on_error="continue",
                next="risk",
            ),
            WorkflowStepDef(
                id="risk",
                type=StepType.SKILL,
                name="Risk assessment",
                skill_id="skill_analysis_risk",
                params={"task": "{{task}}"},
                input_key="risk",
                next="decision",
            ),
            WorkflowStepDef(
                id="decision",
                type=StepType.DECISION,
                name="Go / no-go framing",
                params={
                    "task": "Expansion decision for {{task}}",
                    "options": ["Proceed with pilot", "Defer 90 days", "Do not expand"],
                },
                input_key="decision",
                next="summary",
            ),
            WorkflowStepDef(
                id="summary",
                type=StepType.SKILL,
                name="Executive summary",
                skill_id="skill_reporting_exec_summary",
                params={"task": "{{task}}"},
                input_key="summary",
                next="store",
            ),
            WorkflowStepDef(
                id="store",
                type=StepType.MEMORY,
                name="Store report memory",
                params={
                    "content": "Expansion report completed for: {{task}}",
                    "importance": 0.7,
                },
                input_key="memory",
                next="notify",
            ),
            WorkflowStepDef(
                id="notify",
                type=StepType.NOTIFY,
                name="Notify complete",
                params={"message": "Business expansion report ready for {{task}}"},
                input_key="result",
                next=None,
            ),
        ],
    )


def morning_farm_briefing() -> WorkflowDefinition:
    return WorkflowDefinition(
        id="wfdef_morning_farm_briefing",
        name="morning_farm_briefing",
        version="1.0.0",
        description="Morning agriculture briefing: weather tool → crop plan skill → advice",
        entry="weather",
        tags=["agriculture", "schedule", "morning"],
        steps=[
            WorkflowStepDef(
                id="weather",
                type=StepType.TOOL,
                name="Weather snapshot",
                tool_name="weather",
                params={"location": "{{location}}"},
                input_key="weather",
                on_error="continue",
                next="crop",
            ),
            WorkflowStepDef(
                id="crop",
                type=StepType.SKILL,
                name="Crop planning reminder",
                skill_id="skill_planning_crop",
                params={"task": "{{task}}"},
                input_key="crop_plan",
                next="agri_agent",
            ),
            WorkflowStepDef(
                id="agri_agent",
                type=StepType.AGENT,
                name="Irrigation advice",
                agent_domain="agriculture",
                params={"task": "Create irrigation plan considering: {{task}} weather={{weather}}"},
                input_key="irrigation",
                next="summary",
            ),
            WorkflowStepDef(
                id="summary",
                type=StepType.SKILL,
                name="Morning brief",
                skill_id="skill_reporting_exec_summary",
                params={"task": "Morning farm briefing: {{task}}"},
                input_key="result",
                next=None,
            ),
        ],
    )


def document_ingest_chain() -> WorkflowDefinition:
    return WorkflowDefinition(
        id="wfdef_document_ingest_chain",
        name="document_ingest_chain",
        description="When a document path is provided: note → extract skill → memory",
        entry="set",
        tags=["documents", "event"],
        steps=[
            WorkflowStepDef(
                id="set",
                type=StepType.SET,
                params={"task": "Ingest and summarize document {{path}}"},
                next="outline",
            ),
            WorkflowStepDef(
                id="outline",
                type=StepType.SKILL,
                skill_id="skill_reporting_outline",
                params={"task": "Knowledge extraction report for {{path}}"},
                input_key="outline",
                next="store",
            ),
            WorkflowStepDef(
                id="store",
                type=StepType.MEMORY,
                params={"content": "Document pipeline ran for {{path}}", "importance": 0.55},
                input_key="result",
                next=None,
            ),
        ],
    )


def all_builtin_workflows() -> list[WorkflowDefinition]:
    return [
        business_expansion_report(),
        morning_farm_briefing(),
        document_ingest_chain(),
    ]

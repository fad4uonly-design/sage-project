"""Automation stack tests (v0.4.0)."""

from __future__ import annotations

import pytest

from sage.approval.engine import ApprovalEngine
from sage.approval.models import ApprovalLevel, ApprovalStatus
from sage.audit.logger import ExecutionAudit
from sage.automation.manager import AutomationManager
from sage.core.engine import SageEngine
from sage.tools.interfaces import ToolManager
from sage.workflow.engine import WorkflowEngine
from sage.workflow.models import WorkflowStatus


@pytest.mark.asyncio
async def test_automation_modules_healthy(engine: SageEngine) -> None:
    names = set(engine.registry.names())
    for m in ("workflow", "approval", "audit", "automation", "skills", "tools"):
        assert m in names


@pytest.mark.asyncio
async def test_workflow_business_expansion(engine: SageEngine) -> None:
    wf = engine.container.resolve(WorkflowEngine)  # type: ignore[type-abstract]
    run = await wf.start(
        "business_expansion_report",
        context={"task": "Expand greenhouse produce into city markets"},
        principal="core",
    )
    assert run.status == WorkflowStatus.SUCCEEDED
    assert run.step_history
    assert any(s.status == "succeeded" for s in run.step_history)
    # Result / summary present
    assert run.context.get("summary") or run.result


@pytest.mark.asyncio
async def test_workflow_condition_and_set(engine: SageEngine) -> None:
    from sage.workflow.models import StepType, WorkflowDefinition, WorkflowStepDef

    wf = engine.container.resolve(WorkflowEngine)  # type: ignore[type-abstract]
    defn = WorkflowDefinition(
        id="wfdef_test_cond",
        name="test_condition",
        entry="init",
        steps=[
            WorkflowStepDef(
                id="init",
                type=StepType.SET,
                params={"flag": True, "task": "hello"},
                next="branch",
            ),
            WorkflowStepDef(
                id="branch",
                type=StepType.CONDITION,
                when="flag",
                if_true="yes",
                if_false="no",
            ),
            WorkflowStepDef(
                id="yes",
                type=StepType.SKILL,
                skill_id="skill_decision_recommend",
                params={"task": "{{task}}"},
                input_key="result",
                next=None,
            ),
            WorkflowStepDef(
                id="no",
                type=StepType.SET,
                params={"result": "skipped"},
                next=None,
            ),
        ],
    )
    await wf.register(defn)
    run = await wf.start("test_condition", context={}, principal="core")
    assert run.status == WorkflowStatus.SUCCEEDED
    assert run.context.get("result") is not None


@pytest.mark.asyncio
async def test_approval_deny_and_ask(engine: SageEngine) -> None:
    appr = engine.container.resolve(ApprovalEngine)  # type: ignore[type-abstract]
    await appr.set_policy("tool", "delete_file", ApprovalLevel.DENY)
    decision = await appr.check("tool", "delete_file", "invoke", principal="user")
    assert decision.allowed is False
    assert decision.status == ApprovalStatus.DENIED

    await appr.set_policy("tool", "special_tool", ApprovalLevel.ALWAYS_ASK)
    d2 = await appr.check(
        "tool",
        "special_tool",
        "invoke",
        principal="user",
        auto_approve_in_test=False,
    )
    assert d2.allowed is False
    assert d2.status == ApprovalStatus.PENDING
    assert d2.request is not None
    req = await appr.decide(d2.request.id, approve=True, decided_by="tester")
    assert req.status == ApprovalStatus.APPROVED


@pytest.mark.asyncio
async def test_tools_framework_weather_and_files(engine: SageEngine, tmp_path) -> None:
    tm = engine.container.resolve(ToolManager)  # type: ignore[type-abstract]
    names = {t.name for t in tm.list_tools()}
    assert "weather" in names
    assert "read_file" in names
    assert "write_file" in names
    assert "calculator" in names

    w = await tm.invoke("weather", location="Al Farwaniyah")
    assert w.success
    assert w.output["temp_c"]

    path = tmp_path / "note.txt"
    wr = await tm.invoke("write_file", path=str(path), content="hello sage")
    assert wr.success
    rd = await tm.invoke("read_file", path=str(path))
    assert rd.success
    assert "hello sage" in rd.output


@pytest.mark.asyncio
async def test_execution_audit_records(engine: SageEngine) -> None:
    audit = engine.container.resolve(ExecutionAudit)  # type: ignore[type-abstract]
    rec = await audit.record(
        kind="system",
        status="ok",
        summary="test audit row",
        principal="test",
    )
    assert rec.id
    recent = await audit.list_recent(limit=10)
    assert any(r.id == rec.id for r in recent)


@pytest.mark.asyncio
async def test_automation_manual_job(engine: SageEngine) -> None:
    mgr = engine.container.resolve(AutomationManager)  # type: ignore[type-abstract]
    jobs = await mgr.list_jobs()
    assert any(j.name == "on_document_ingested" for j in jobs)

    # Enable and run morning briefing workflow job
    await mgr.enable("morning_farm_briefing", True)
    result = await mgr.run_job(
        "morning_farm_briefing",
        context={"task": "tomatoes morning check", "location": "Kuwait"},
    )
    assert result["name"] == "morning_farm_briefing"
    # Should succeed end-to-end with stub weather + skills + agent
    assert result.get("success") is True
    assert result.get("workflow_run_id")


@pytest.mark.asyncio
async def test_workflow_list_builtin(engine: SageEngine) -> None:
    wf = engine.container.resolve(WorkflowEngine)  # type: ignore[type-abstract]
    defs = await wf.list_definitions()
    names = {d.name for d in defs}
    assert "business_expansion_report" in names
    assert "morning_farm_briefing" in names

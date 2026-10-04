"""Integration: full engine boot and conversation."""

from __future__ import annotations

import pytest
from sage.core.engine import EngineState, SageEngine


@pytest.mark.asyncio
async def test_boot_and_health(engine: SageEngine) -> None:
    assert engine.state in (EngineState.RUNNING, EngineState.DEGRADED)
    health = await engine.health()
    assert health.is_ready
    names = {m.name for m in health.modules}
    for required in ("database", "memory", "conversation", "orchestrator", "knowledge"):
        assert required in names


@pytest.mark.asyncio
async def test_ask_remember_recall(engine: SageEngine) -> None:
    reply = await engine.ask("remember: My favorite crop is basil")
    assert "remember" in reply.lower() or "basil" in reply.lower()

    reply2 = await engine.ask("what do you remember about basil")
    assert "basil" in reply2.lower()


@pytest.mark.asyncio
async def test_ask_plan(engine: SageEngine) -> None:
    reply = await engine.ask("plan a weekly study schedule for Python")
    assert "step" in reply.lower() or "plan" in reply.lower() or "1." in reply


@pytest.mark.asyncio
async def test_status_dict(engine: SageEngine) -> None:
    st = engine.status_dict()
    assert st["version"]
    assert st["modules"]
    assert st["boot"]["success"] is True


@pytest.mark.asyncio
async def test_ask_calculator_runs_the_complete_user_facing_tool_loop(
    engine: SageEngine,
) -> None:
    """ONE continuous user-facing run proves the complete governed tool loop.

    Entry (``SageEngine.ask`` → conversation session → orchestrator) → real
    intent routing → permission + approval through the live runtime seam →
    execution → Tool-R0 verification → real audit (tool and capability records)
    → the verified value in the user-facing response.

    Nothing is stubbed: this is the ordinary booted engine, so the analyzer,
    ``DefaultToolManager``, ``PermissionManager``, ``ApprovalEngine``,
    ``ToolOutputVerifier`` and ``ExecutionAudit`` are the production ones.
    """
    from sage.audit.logger import ExecutionAudit

    reply = await engine.ask("what is 15 plus 30")

    # 8. The verified value reaches the user-facing response.
    assert "45" in reply

    audit = engine.container.resolve(ExecutionAudit)

    # 6. A real tool audit record — written deep inside
    #    ``DefaultToolManager.invoke``, past the permission/approval/verification
    #    seam, so its presence proves all of those ran on the real path.
    tool_records = [
        r
        for r in await audit.list_recent(limit=50, kind="tool")
        if r.tool_name == "calculator"
    ]
    assert tool_records, "the calculator must be audited through the real tool seam"
    tool_record = tool_records[-1]
    assert tool_record.status == "ok"
    assert tool_record.principal == "core"  # the manager's real principal

    # 7. A real capability audit record for the same request.
    capability_records = [
        r
        for r in await audit.list_recent(limit=50, kind="capability")
        if r.detail.get("tool") == "calculator"
    ]
    assert capability_records, "the request itself must be audited"
    record = capability_records[-1]

    # 2. Real intent + understanding ran within this same request
    #    (capability = intent kind; conversation_mode = understanding layer).
    assert record.detail["capability"] == "tool"
    assert record.detail.get("conversation_mode")

    # 3 & 4. Execution went through the real ToolManager (permission and
    #        approval live inside it): the recorded step trace shows a
    #        successful invocation and no failed step.
    steps = {s["step"]: s["ok"] for s in record.detail["steps"]}
    assert steps.get("invoke_tool") is True
    assert record.detail["failed_steps"] == []

    # 5. The result was verified, not merely executed.
    assert record.detail["verification"]["verified"] is True

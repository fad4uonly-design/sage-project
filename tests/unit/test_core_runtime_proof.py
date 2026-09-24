"""Core runtime proof tests — approval, permission, step bound, flagged results."""
from __future__ import annotations

from typing import Any

import pytest
from sage.approval.engine import ApprovalEngine
from sage.approval.models import ApprovalLevel
from sage.audit.logger import ExecutionAudit
from sage.core.engine import SageEngine
from sage.models.interfaces import CompletionResponse, ModelRouter
from sage.orchestrator.interfaces import Orchestrator
from sage.orchestrator.models import Intent, IntentKind, PipelineStep
from sage.permissions.interfaces import PermissionManager
from sage.reasoning.engine import DefaultReasoningEngine
from sage.reasoning.interfaces import ReasoningEngine
from sage.tools.base import BaseTool
from sage.tools.builtin.core_tools import CalculatorTool
from sage.tools.interfaces import ToolManager, ToolResult
from sage.tools.manager import DefaultToolManager
from sage.tools.observation import build_tool_observation
from sage.tools.verification import ToolOutputVerifier, build_verifier

TOOL_STEPS = [PipelineStep.ANALYZE_INTENT, PipelineStep.INVOKE_TOOL, PipelineStep.COMPOSE_RESPONSE]


class _RecordingLanguageModel:
    provider = "recording"
    model_name = "recording-v1"
    def __init__(self, *, reply: str = "Recorded conclusion.") -> None:
        self.reply = reply
        self.requests: list[Any] = []
    async def complete(self, request: Any) -> CompletionResponse:
        self.requests.append(request)
        return CompletionResponse(content=self.reply, model=self.model_name, provider=self.provider, usage={}, raw={}, finish_reason="stop")


class _DecisionLanguageModel:
    provider = "decision"
    model_name = "decision-v1"
    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.requests: list[Any] = []
    async def complete(self, request: Any) -> CompletionResponse:
        self.requests.append(request)
        content = self._replies.pop(0) if self._replies else "Done.\nFINAL"
        return CompletionResponse(content=content, model=self.model_name, provider=self.provider, usage={}, raw={}, finish_reason="stop")


class _RecordingModelRouter:
    def __init__(self, lm: Any) -> None:
        self.language_model = lm
    def get_language_model(self, *, capability: str | None = None) -> Any:
        return self.language_model
    def get_embedding_model(self) -> None:
        return None


class _CountingToolManager:
    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.invocations: list[tuple[str, dict[str, Any]]] = []
        self.results: list[ToolResult] = []
    def register(self, tool: Any) -> None:
        self._inner.register(tool)
    def list_tools(self) -> list[Any]:
        return self._inner.list_tools()
    async def invoke(self, name: str, **params: Any) -> ToolResult:
        self.invocations.append((name, params))
        result = await self._inner.invoke(name, **params)
        self.results.append(result)
        return result


class _StubAnalyzer:
    def __init__(self, intent: Intent) -> None:
        self._intent = intent
    def analyze(self, message: str, *, context: Any = None) -> Intent:
        return self._intent


def _tool_intent(message: str, tool: str, args: dict[str, Any]) -> Intent:
    return Intent(kind=IntentKind.TOOL, confidence=1.0, raw_message=message, subject=message, entities={"tool": tool, "args": args})


def _steps(result: Any) -> list[PipelineStep]:
    return [s.step for s in result.steps]


class CountingCalculator(CalculatorTool):
    def __init__(self) -> None:
        self.executions = 0
    async def execute(self, **params: Any) -> ToolResult:
        self.executions += 1
        return await super().execute(**params)


class GatedProbeTool(BaseTool):
    name = "gated_probe"
    description = "Permission-gated probe."
    category = "utility"
    permissions = ["tools.invoke"]
    parameters_schema = {"type": "object", "properties": {}}
    def __init__(self) -> None:
        self.executions = 0
    async def execute(self, **params: Any) -> ToolResult:
        self.executions += 1
        return ToolResult(success=True, output="GATED-OK")


class InsightTool(BaseTool):
    name = "insight"
    description = "Summarize a numeric series."
    category = "utility"
    interpretable = True
    parameters_schema = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
    def __init__(self) -> None:
        self.executions = 0
    async def execute(self, **params: Any) -> ToolResult:
        self.executions += 1
        return ToolResult(success=True, output=f"trend-up:{params.get('text', '')}")


class NullInsightTool(BaseTool):
    name = "null_insight"
    description = "Succeeds with None output."
    category = "utility"
    interpretable = True
    parameters_schema = {"type": "object", "properties": {}}
    def __init__(self) -> None:
        self.executions = 0
    async def execute(self, **params: Any) -> ToolResult:
        self.executions += 1
        return ToolResult(success=True, output=None)


@pytest.mark.asyncio
async def test_approval_deny_blocks_execution_at_runtime(engine: SageEngine) -> None:
    router = _RecordingModelRouter(_RecordingLanguageModel())
    engine.container.register_instance(ModelRouter, router)
    engine.container.register_instance(ReasoningEngine, DefaultReasoningEngine(models=router))
    pm = engine.container.resolve(PermissionManager)  # type: ignore[type-abstract]
    approval = engine.container.resolve(ApprovalEngine)  # type: ignore[type-abstract]
    audit = engine.container.resolve(ExecutionAudit)
    real_manager = DefaultToolManager(pm, principal="core", approval_engine=approval, audit=audit, auto_approve_in_test=False, verifier=build_verifier())
    manager = _CountingToolManager(real_manager)
    engine.container.register_instance(ToolManager, manager)
    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]
    calc = CountingCalculator()
    manager.register(calc)
    await approval.set_policy("tool", "calculator", ApprovalLevel.DENY, principal="core")
    result = await orch.handle("calculate 12*13")
    assert calc.executions == 0
    assert manager.results and manager.results[0].success is False
    assert manager.results[0].metadata.get("approval_status") == "denied"
    assert "156" not in result.response
    assert "Denied by policy" in result.response
    assert PipelineStep.REASON not in _steps(result)


@pytest.mark.asyncio
async def test_approval_pending_blocks_execution_and_surfaces_request(engine: SageEngine) -> None:
    router = _RecordingModelRouter(_RecordingLanguageModel())
    engine.container.register_instance(ModelRouter, router)
    engine.container.register_instance(ReasoningEngine, DefaultReasoningEngine(models=router))
    pm = engine.container.resolve(PermissionManager)  # type: ignore[type-abstract]
    approval = engine.container.resolve(ApprovalEngine)  # type: ignore[type-abstract]
    audit = engine.container.resolve(ExecutionAudit)
    real_manager = DefaultToolManager(pm, principal="core", approval_engine=approval, audit=audit, auto_approve_in_test=False, verifier=build_verifier())
    manager = _CountingToolManager(real_manager)
    engine.container.register_instance(ToolManager, manager)
    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]
    calc = CountingCalculator()
    manager.register(calc)
    await approval.set_policy("tool", "calculator", ApprovalLevel.ALWAYS_ASK, principal="core")
    result = await orch.handle("calculate 12*13")
    assert calc.executions == 0
    assert manager.results and manager.results[0].success is False
    assert manager.results[0].metadata.get("approval_status") == "pending"
    assert manager.results[0].metadata.get("approval_request_id")
    assert "156" not in result.response
    assert "Approval required" in result.response
    pending = await approval.list_pending()
    assert any(r.resource_id == "calculator" and r.status.value == "pending" for r in pending)


@pytest.mark.asyncio
async def test_permission_denied_blocks_execution_at_runtime(engine: SageEngine) -> None:
    pm = engine.container.resolve(PermissionManager)  # type: ignore[type-abstract]
    approval = engine.container.resolve(ApprovalEngine)  # type: ignore[type-abstract]
    gated = DefaultToolManager(pm, principal="plugin.demo", approval_engine=approval, audit=None, auto_approve_in_test=True, verifier=ToolOutputVerifier(strict=False))
    probe = GatedProbeTool()
    gated.register(probe)
    engine.container.register_instance(ToolManager, gated)
    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]
    orch._analyzer = _StubAnalyzer(_tool_intent("probe the gate", "gated_probe", {}))  # noqa: SLF001
    result = await orch.handle("probe the gate")
    assert probe.executions == 0
    assert "GATED-OK" not in result.response
    assert "Permission denied" in result.response
    assert result.intent.kind == IntentKind.TOOL
    follow_up = await orch.handle("hello there")
    assert follow_up.response


class TimeProbeTool(BaseTool):
    name = "current_time"
    description = "Time probe double."
    category = "utility"
    interpretable = True
    parameters_schema = {"type": "object", "properties": {}}
    def __init__(self) -> None:
        self.executions = 0
    async def execute(self, **params: Any) -> ToolResult:
        self.executions += 1
        return ToolResult(success=True, output="2026-09-23T11:35:29+03:00")


@pytest.mark.asyncio
async def test_bounded_loop_stops_after_three_tool_invocations(engine: SageEngine) -> None:
    from sage.audit.logger import ExecutionAudit
    replies = [f'More.\nNEXT_TOOL: {{"tool": "current_time", "arguments": {{"note": "n{i}"}}}}' for i in range(8)]
    router = _RecordingModelRouter(_DecisionLanguageModel(replies))
    engine.container.register_instance(ModelRouter, router)
    engine.container.register_instance(ReasoningEngine, DefaultReasoningEngine(models=router))
    manager = _CountingToolManager(engine.container.resolve(ToolManager))
    engine.container.register_instance(ToolManager, manager)
    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]
    insight = InsightTool()
    probe = TimeProbeTool()
    manager.register(insight)
    manager.register(probe)
    orch._analyzer = _StubAnalyzer(_tool_intent("interpret the series q1", "insight", {"text": "q1"}))  # noqa: SLF001
    from sage.orchestrator.engine import _MAX_TOOL_DECISION_ITERATIONS
    result = await orch.handle("interpret the series q1")
    assert insight.executions + probe.executions == 3
    assert len(manager.invocations) == 3
    assert len(router.language_model.requests) == 3
    assert result.response
    assert "NEXT_TOOL" not in result.response
    audit = engine.container.resolve(ExecutionAudit)
    record = next(r for r in await audit.list_recent(kind="capability", limit=10) if r.subject_id == result.plan_id)
    assert record.detail["tool_decision_iterations"] == _MAX_TOOL_DECISION_ITERATIONS


@pytest.mark.asyncio
async def test_flagged_result_skips_reasoning_and_is_not_verified(engine: SageEngine) -> None:
    router = _RecordingModelRouter(_RecordingLanguageModel(reply="Must not be used."))
    engine.container.register_instance(ModelRouter, router)
    engine.container.register_instance(ReasoningEngine, DefaultReasoningEngine(models=router))
    pm = engine.container.resolve(PermissionManager)  # type: ignore[type-abstract]
    approval = engine.container.resolve(ApprovalEngine)  # type: ignore[type-abstract]
    strict_manager = DefaultToolManager(pm, principal="core", approval_engine=approval, audit=None, auto_approve_in_test=True, verifier=ToolOutputVerifier(strict=True))
    null_tool = NullInsightTool()
    strict_manager.register(null_tool)
    engine.container.register_instance(ToolManager, strict_manager)
    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]
    orch._analyzer = _StubAnalyzer(_tool_intent("interpret nothing", "null_insight", {}))  # noqa: SLF001
    result = await orch.handle("interpret nothing")
    assert null_tool.executions == 1
    assert router.language_model.requests == []
    assert _steps(result) == TOOL_STEPS
    assert "flagged" in result.response
    assert "verified" not in result.response.lower()


def test_flagged_observation_renders_as_flagged_data() -> None:
    result = ToolResult(success=True, output="some-output", metadata={"verification": {"verified": False, "confidence": 0.5, "issue_count": 1}, "verification_issues": [{"severity": "error", "category": "missing_error", "message": "boom", "field": None}]})
    obs = build_tool_observation(tool_name="probe", arguments={}, result=result)
    assert "<tool_observation>" in obs
    assert "verification: flagged" in obs
    assert "verification: verified" not in obs


@pytest.mark.asyncio
async def test_real_calculator_runtime_returns_verified_45(engine: SageEngine) -> None:
    router = _RecordingModelRouter(_RecordingLanguageModel())
    engine.container.register_instance(ModelRouter, router)
    engine.container.register_instance(ReasoningEngine, DefaultReasoningEngine(models=router))
    manager = _CountingToolManager(engine.container.resolve(ToolManager))
    engine.container.register_instance(ToolManager, manager)
    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]
    result = await orch.handle("what is 15 plus 30")
    assert result.intent.kind == IntentKind.TOOL
    assert result.intent.entities.get("tool") == "calculator"
    assert len(manager.invocations) == 1
    assert manager.results[0].metadata.get("verification", {}).get("verified") is True
    assert result.response.splitlines()[0] == "45"
    assert router.language_model.requests == []

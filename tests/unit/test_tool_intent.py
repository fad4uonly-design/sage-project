"""Unit tests for the explicit tool-invocation path (Phase 2 E2E glue).

Deterministic — no engine boot, no network, no model. Covers:

* "learn about X" maps to IntentKind.TOOL → web_learn with a topic entity
* regression: all pre-existing intents still classify exactly as before
* TOOL plans run [INVOKE_TOOL, COMPOSE_RESPONSE]
* the orchestrator loop through a duck-typed ToolManager: success, controlled
  failure, crashing tool (step-level containment), and unknown tool
"""

from __future__ import annotations

from typing import Any

import pytest

from sage.core.container import Container
from sage.orchestrator.engine import DefaultOrchestrator
from sage.orchestrator.models import IntentKind, PipelineStep
from sage.tools.interfaces import ToolManager, ToolResult
from sage.tools.manager import DefaultToolManager


class FakeToolManager:
    """Duck-typed ToolManager: records invocations, returns a canned result."""

    def __init__(self, result: ToolResult | None = None, exc: Exception | None = None) -> None:
        self._result = result
        self._exc = exc
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def register(self, tool: Any) -> None:  # pragma: no cover - must not be called
        raise AssertionError("orchestrator must never register tools itself")

    def list_tools(self) -> list[Any]:  # pragma: no cover - must not be called
        return []

    async def invoke(self, name: str, **params: Any) -> ToolResult:
        self.calls.append((name, params))
        if self._exc is not None:
            raise self._exc
        assert self._result is not None
        return self._result


def make_orchestrator(manager: Any) -> DefaultOrchestrator:
    container = Container()
    if manager is not None:
        container.register_instance(ToolManager, manager)
    return DefaultOrchestrator(container)


# -- Intent mapping -----------------------------------------------------------


async def test_learn_about_maps_to_tool_intent() -> None:
    orch = make_orchestrator(None)
    intent = await orch.analyze_intent("Learn about photosynthesis")
    assert intent.kind == IntentKind.TOOL
    assert intent.entities["tool"] == "web_learn"
    assert intent.entities["args"] == {"topic": "photosynthesis"}
    assert intent.subject == "photosynthesis"


async def test_learn_about_strips_punctuation_and_matches_case() -> None:
    orch = make_orchestrator(None)
    intent = await orch.analyze_intent("learn up about The Water Cycle?")
    assert intent.kind == IntentKind.TOOL
    assert intent.entities["args"] == {"topic": "The Water Cycle"}


async def test_learn_about_beats_domain_keyword_routing() -> None:
    """An explicit learning imperative is never hijacked by domain keywords."""
    orch = make_orchestrator(None)
    intent = await orch.analyze_intent("learn about swot analysis")
    assert intent.kind == IntentKind.TOOL
    assert intent.entities["tool"] == "web_learn"


# -- Calculator explicit imperative --------------------------------------------


async def test_calculate_maps_to_calculator_intent() -> None:
    orch = make_orchestrator(None)
    intent = await orch.analyze_intent("calculate 25 * 4")
    assert intent.kind == IntentKind.TOOL
    assert intent.entities["tool"] == "calculator"
    assert intent.entities["args"] == {"expression": "25 * 4"}
    assert intent.subject == "25 * 4"


async def test_calculate_pattern_case_and_punctuation_handling() -> None:
    """Case-insensitive prefix, trailing punctuation stripped — same contract
    as the web_learn pattern."""
    orch = make_orchestrator(None)
    intent = await orch.analyze_intent("CALCULATE 100 / 5 + 1?")
    assert intent.kind == IntentKind.TOOL
    assert intent.entities["tool"] == "calculator"
    assert intent.entities["args"] == {"expression": "100 / 5 + 1"}
    assert intent.subject == "100 / 5 + 1"


async def test_calculator_plan_runs_invoke_then_compose() -> None:
    manager = FakeToolManager(
        ToolResult(success=True, output={"expression": "25 * 4", "result": 100}, metadata={})
    )
    orch = make_orchestrator(manager)
    result = await orch.handle("calculate 25 * 4")
    assert [s.step for s in result.steps] == [
        PipelineStep.ANALYZE_INTENT,
        PipelineStep.INVOKE_TOOL,
        PipelineStep.COMPOSE_RESPONSE,
    ]
    assert manager.calls == [("calculator", {"expression": "25 * 4"})]
    assert all(s.success for s in result.steps)
    assert "100" in result.response


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("remember: buy milk", IntentKind.REMEMBER),
        ("Remember that my test project is called SAGE.", IntentKind.REMEMBER),
        ("what do you remember about milk", IntentKind.RECALL),
        ("plan my week", IntentKind.PLAN),
        ("reason about database backups", IntentKind.REASON),
        ("research solar panels", IntentKind.RESEARCH),
        ("status", IntentKind.STATUS),
        ("hello there", IntentKind.CHAT),
        ("calculate 25 * 4", IntentKind.TOOL),
        # Priority intents beat explicit tool imperatives.
        ("Remember: calculate 2 + 2 first", IntentKind.REMEMBER),
    ],
)
async def test_existing_intents_unchanged(message: str, expected: IntentKind) -> None:
    orch = make_orchestrator(None)
    intent = await orch.analyze_intent(message)
    assert intent.kind == expected


# -- Plan shape ---------------------------------------------------------------


async def test_tool_plan_runs_invoke_then_compose() -> None:
    manager = FakeToolManager(
        ToolResult(success=True, output={"topic": "t", "summary": "s"}, metadata={})
    )
    orch = make_orchestrator(manager)
    result = await orch.handle("learn about t")
    assert [s.step for s in result.steps] == [
        PipelineStep.ANALYZE_INTENT,
        PipelineStep.INVOKE_TOOL,
        PipelineStep.COMPOSE_RESPONSE,
    ]
    assert all(s.success for s in result.steps)


# -- Orchestrator loop through a ToolManager ----------------------------------


async def test_tool_loop_success_returns_tool_artifact() -> None:
    manager = FakeToolManager(
        ToolResult(
            success=True,
            output={
                "topic": "photosynthesis",
                "summary": "Plants convert light into chemical energy.",
                "sources": ["https://example.com/a", "https://example.com/b"],
            },
            metadata={"served_from": "web"},
        )
    )
    orch = make_orchestrator(manager)

    result = await orch.handle("Learn about photosynthesis")

    assert result.intent.kind == IntentKind.TOOL
    assert manager.calls == [("web_learn", {"topic": "photosynthesis"})]
    assert "Plants convert light into chemical energy." in result.response
    assert "https://example.com/a" in result.response
    assert all(s.success for s in result.steps)


async def test_tool_failure_is_controlled_and_loop_survives() -> None:
    manager = FakeToolManager(
        ToolResult(success=False, error="no usable search results for topic: 'x'")
    )
    orch = make_orchestrator(manager)

    result = await orch.handle("Learn about quantum knitting")

    assert result.intent.kind == IntentKind.TOOL
    assert "couldn't complete" in result.response
    assert "no usable search results" in result.response

    # The loop stays healthy for the next request.
    follow_up = await orch.handle("hello there")
    assert follow_up.response


async def test_crashing_tool_is_contained_at_step_level() -> None:
    manager = FakeToolManager(exc=RuntimeError("connection refused"))
    orch = make_orchestrator(manager)

    result = await orch.handle("Learn about brittle things")

    assert result.intent.kind == IntentKind.TOOL
    invoke_results = [s for s in result.steps if s.step == PipelineStep.INVOKE_TOOL]
    assert invoke_results and not invoke_results[0].success
    assert "connection refused" in (invoke_results[0].error or "")
    # Controlled fallback — the orchestrator did not propagate the exception.
    assert "did not produce a result" in result.response


async def test_unknown_tool_reports_failure_without_crashing() -> None:
    orch = make_orchestrator(DefaultToolManager())  # no tools registered

    result = await orch.handle("Learn about anything")

    assert result.intent.kind == IntentKind.TOOL
    assert "Unknown tool: web_learn" in result.response


async def test_missing_tool_manager_is_controlled() -> None:
    orch = make_orchestrator(None)  # empty container: no ToolManager at all

    result = await orch.handle("Learn about anything")

    assert "tool framework is unavailable" in result.response.lower()

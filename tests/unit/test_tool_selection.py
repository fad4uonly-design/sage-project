"""Tool-calling reliability tests — schema-constrained decision, existing execution.

The configured local brain (``gemma3:4b``) reports only ``completion`` and
``vision`` in Ollama's capability list, so SAGE must NOT send a native
``tools`` payload. The decision instead travels as a genuine structured-output
request: an explicit JSON schema on the existing ``CompletionRequest``, which
the local adapter translates to ``response_format`` (see
``sage/tools/selection.py``).

Two properties are pinned here:

* structured output — the decision request carries an explicit schema, while
  ordinary free-form generation carries none;
* tool calling — a decision can only name a *registered* tool, execution still
  goes through the existing ``ToolManager``, and every failure path degrades to
  ordinary composition instead of fabricating a tool result.

Deterministic and offline: no engine boot, no network, no live model.
"""

from __future__ import annotations

from typing import Any

import pytest
from sage.core.container import Container
from sage.models.interfaces import (
    CompletionRequest,
    CompletionResponse,
    Message,
    ModelRouter,
)
from sage.models.local._adapter import LocalLanguageModel
from sage.orchestrator.engine import DefaultOrchestrator
from sage.orchestrator.models import IntentKind, PipelineStep
from sage.tools.interfaces import ToolInfo, ToolManager, ToolResult
from sage.tools.selection import (
    ModelToolSelector,
    _parse_decision,
    build_decision_schema,
)

# A turn the conversation layer already marks as a tool request (mode
# ``tool_request`` → ``policy.allow_tools``), so the selector is consulted.
TOOL_REQUEST_MESSAGE = "can you compute 12 + 30?"

# A plain question: policy forbids tools, so no decision call is made.
PLAIN_QUESTION = "What is RAG?"

CALCULATOR_DECISION = (
    '{"tool": "calculator", "arguments": {"expression": "12 + 30"}}'
)
# Deliberately contains no digits that the tool result ("42") could be
# confused with, so "the tool did not run" is unambiguous in assertions.
FREE_FORM_REPLY = "Here is my answer."

CALCULATOR = ToolInfo(
    name="calculator",
    description="Evaluate a simple arithmetic expression (safe AST evaluator).",
    category="utility",
    parameters_schema={
        "type": "object",
        "properties": {"expression": {"type": "string"}},
        "required": ["expression"],
    },
)

CURRENT_TIME = ToolInfo(
    name="current_time",
    description="Return the current UTC time in ISO-8601 format.",
    category="utility",
    parameters_schema={"type": "object", "properties": {}},
)
# -- Doubles ------------------------------------------------------------------


class ScriptedLanguageModel:
    """Returns queued replies and records every request it was handed."""

    provider = "scripted"
    model_name = "scripted-v1"

    def __init__(self, replies: list[str] | None = None, exc: Exception | None = None) -> None:
        self._replies = list(replies or [])
        self._exc = exc
        self.requests: list[CompletionRequest] = []

    @property
    def calls(self) -> int:
        return len(self.requests)

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.requests.append(request)
        if self._exc is not None:
            raise self._exc
        content = self._replies.pop(0) if self._replies else FREE_FORM_REPLY
        return CompletionResponse(
            content=content,
            model=self.model_name,
            provider=self.provider,
            usage={},
            raw={},
            finish_reason="stop",
        )


class ScriptedRouter:
    """ModelRouter double handing out one scripted language model."""

    def __init__(self, model: ScriptedLanguageModel) -> None:
        self.lm = model

    def get_language_model(self, *, capability: str | None = None) -> ScriptedLanguageModel:
        return self.lm

    def get_embedding_model(self) -> None:
        return None


class FakeToolManager:
    """Existing ToolManager contract, backed by in-memory tool metadata."""

    def __init__(
        self,
        tools: list[ToolInfo] | None = None,
        result: ToolResult | None = None,
    ) -> None:
        self._tools = list(tools if tools is not None else [CALCULATOR, CURRENT_TIME])
        self._result = result or ToolResult(success=True, output="42")
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def register(self, tool: Any) -> None:  # pragma: no cover - not used here
        raise AssertionError("the orchestrator must never register tools itself")

    def list_tools(self) -> list[ToolInfo]:
        return list(self._tools)

    async def invoke(self, name: str, **params: Any) -> ToolResult:
        self.calls.append((name, params))
        return self._result


def build(registrations: dict[Any, Any]) -> DefaultOrchestrator:
    """Bare container + orchestrator; only the given Protocol keys are wired."""
    container = Container()
    for key, value in registrations.items():
        if value is not None:
            container.register_instance(key, value)
    return DefaultOrchestrator(container)

# -- Structured output --------------------------------------------------------


def test_decision_schema_restricts_tool_to_registered_names() -> None:
    schema = build_decision_schema(["calculator", "current_time"])

    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["tool", "arguments"]
    assert schema["properties"]["tool"]["enum"] == [
        "calculator",
        "current_time",
        None,
    ]


async def test_tool_decision_request_carries_explicit_json_schema() -> None:
    model = ScriptedLanguageModel([CALCULATOR_DECISION])
    selector = ModelToolSelector(ScriptedRouter(model), FakeToolManager())

    decision = await selector.decide(TOOL_REQUEST_MESSAGE)

    assert decision == ("calculator", {"expression": "12 + 30"})
    assert len(model.requests) == 1
    request = model.requests[0]
    assert request.response_schema is not None
    assert request.response_schema["properties"]["tool"]["enum"] == [
        "calculator",
        "current_time",
        None,
    ]
    # The registry is the source of truth for the catalog and the enum.
    system = request.messages[0].content
    assert "calculator" in system and "expression (required)" in system


async def test_free_form_generation_receives_no_structured_constraint() -> None:
    model = ScriptedLanguageModel([FREE_FORM_REPLY])
    orch = build({ModelRouter: ScriptedRouter(model)})

    result = await orch.handle(PLAIN_QUESTION)

    assert result.response == FREE_FORM_REPLY
    assert model.calls == 1
    assert model.requests[0].response_schema is None


async def test_plain_question_does_not_consult_tool_selection() -> None:
    model = ScriptedLanguageModel([FREE_FORM_REPLY])
    tools = FakeToolManager()
    orch = build({ModelRouter: ScriptedRouter(model), ToolManager: tools})

    await orch.handle(PLAIN_QUESTION)

    # One model call only — ordinary composition, not a tool decision.
    assert model.calls == 1
    assert tools.calls == []


# -- Tool calling -------------------------------------------------------------


async def test_decision_selects_tool_without_native_tools_payload() -> None:
    model = ScriptedLanguageModel([CALCULATOR_DECISION])
    orch = build({
        ModelRouter: ScriptedRouter(model),
        ToolManager: FakeToolManager(),
    })

    result = await orch.handle(TOOL_REQUEST_MESSAGE)

    assert result.intent.kind == IntentKind.TOOL
    assert result.intent.entities["tool"] == "calculator"
    assert result.response == "42"
    # Structured JSON only: the adapter is never asked for native tool calling.
    assert model.calls == 1
    assert "tools" not in model.requests[0].model_dump()


async def test_selected_tool_executes_through_existing_manager() -> None:
    model = ScriptedLanguageModel([CALCULATOR_DECISION])
    tools = FakeToolManager()
    orch = build({ModelRouter: ScriptedRouter(model), ToolManager: tools})

    result = await orch.handle(TOOL_REQUEST_MESSAGE)

    assert tools.calls == [("calculator", {"expression": "12 + 30"})]
    assert [step.step for step in result.steps] == [
        PipelineStep.ANALYZE_INTENT,
        PipelineStep.INVOKE_TOOL,
        PipelineStep.COMPOSE_RESPONSE,
    ]


async def test_null_decision_falls_back_to_ordinary_composition() -> None:
    model = ScriptedLanguageModel(['{"tool": null, "arguments": {}}', FREE_FORM_REPLY])
    tools = FakeToolManager()
    orch = build({ModelRouter: ScriptedRouter(model), ToolManager: tools})

    result = await orch.handle(TOOL_REQUEST_MESSAGE)

    assert result.intent.kind == IntentKind.CHAT
    assert result.response == FREE_FORM_REPLY
    assert tools.calls == []


async def test_unregistered_tool_in_decision_is_refused() -> None:
    model = ScriptedLanguageModel(
        ['{"tool": "rm_rf", "arguments": {}}', FREE_FORM_REPLY]
    )
    tools = FakeToolManager()
    orch = build({ModelRouter: ScriptedRouter(model), ToolManager: tools})

    result = await orch.handle(TOOL_REQUEST_MESSAGE)

    # The model cannot reach a tool outside the existing registry.
    assert tools.calls == []
    assert result.intent.kind == IntentKind.CHAT
    assert result.response == FREE_FORM_REPLY


async def test_malformed_decision_does_not_fabricate_a_tool_result() -> None:
    model = ScriptedLanguageModel(["not json at all", FREE_FORM_REPLY])
    tools = FakeToolManager()
    orch = build({ModelRouter: ScriptedRouter(model), ToolManager: tools})

    result = await orch.handle(TOOL_REQUEST_MESSAGE)

    assert tools.calls == []
    assert result.response == FREE_FORM_REPLY


async def test_selector_failure_degrades_to_ordinary_composition() -> None:
    model = ScriptedLanguageModel(exc=RuntimeError("local model unavailable"))
    tools = FakeToolManager()
    orch = build({ModelRouter: ScriptedRouter(model), ToolManager: tools})

    result = await orch.handle(TOOL_REQUEST_MESSAGE)

    assert tools.calls == []
    assert result.intent.kind == IntentKind.CHAT
    # No model output exists — SAGE must not claim a tool ran.
    assert "42" not in result.response


async def test_failed_tool_execution_is_not_reported_as_success() -> None:
    model = ScriptedLanguageModel([CALCULATOR_DECISION])
    tools = FakeToolManager(result=ToolResult(success=False, error="division by zero"))
    orch = build({ModelRouter: ScriptedRouter(model), ToolManager: tools})

    result = await orch.handle(TOOL_REQUEST_MESSAGE)

    assert tools.calls == [("calculator", {"expression": "12 + 30"})]
    # The existing failure policy is preserved: an honest failure, no invented
    # successful output and no fall-through to a fabricated chat answer.
    assert "division by zero" in result.response
    assert "42" not in result.response


async def test_explicit_imperative_still_skips_the_model() -> None:
    # Deterministic imperatives remain the first path — no decision call at all.
    model = ScriptedLanguageModel([CALCULATOR_DECISION])
    tools = FakeToolManager()
    orch = build({ModelRouter: ScriptedRouter(model), ToolManager: tools})

    result = await orch.handle("calculate 25 * 4")

    assert result.intent.kind == IntentKind.TOOL
    assert tools.calls == [("calculator", {"expression": "25 * 4"})]
    assert model.calls == 0
async def test_free_form_reply_never_uses_native_tools() -> None:
    # gemma3:4b is not tool-capable in Ollama, so a normal completion must stay
    # a plain request with no ``tools`` payload and no structured constraint.
    model = ScriptedLanguageModel(["Hey there!"])
    orch = build({ModelRouter: ScriptedRouter(model)})

    await orch.handle("say hello")

    assert model.calls == 1
    dumped = model.requests[0].model_dump()
    assert "tools" not in dumped
    assert trapped_is_absent(dumped)


def trapped_is_absent(payload: dict[str, Any]) -> bool:
    """No native tool-call plumbing anywhere in the outgoing request."""
    return not any(
        key in payload for key in ("tools", "tool_choice", "functions", "function_call")
    )


# -- Adapter translation (existing local adapter, no new client) --------------


def test_local_adapter_translates_schema_into_ollama_format() -> None:
    adapter = LocalLanguageModel(base_url="http://127.0.0.1:11434/v1", model_name="gemma3:4b")
    schema = build_decision_schema(["calculator"])
    body = adapter.build_payload(
        CompletionRequest(
            messages=[Message(role="user", content="compute 12 + 30")],
            response_schema=schema,
        )
    )

    # Existing OpenAI-compatible endpoint, explicit schema — not ``format: "json"``.
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "sage_response", "schema": schema},
    }
    assert "tools" not in body
    assert body["model"] == "gemma3:4b"


def test_local_adapter_omits_response_format_for_free_form() -> None:
    adapter = LocalLanguageModel(base_url="http://127.0.0.1:11434/v1", model_name="gemma3:4b")
    body = adapter.build_payload(
        CompletionRequest(messages=[Message(role="user", content="hi")])
    )

    assert "response_format" not in body


@pytest.mark.parametrize(
    "reply",
    [
        "",
        "not json",
        "[]",
        '{"tool": 42, "arguments": {}}',
        '{"tool": "calculator", "arguments": "25 * 4"}',
        '{"tool": "", "arguments": {}}',
    ],
)
def test_unusable_decisions_are_rejected(reply: str) -> None:
    assert _parse_decision(reply, ["calculator", "current_time"]) is None


def test_missing_arguments_default_to_empty_map() -> None:
    # Absent arguments are not a decision error: the existing ToolManager is the
    # component that validates required parameters, so parsing stays permissive.
    assert _parse_decision('{"tool": "current_time"}', ["current_time"]) == (
        "current_time",
        {},
    )


async def test_required_argument_still_enforced_before_invocation() -> None:
    # A decision that names a registered tool but omits a required argument is
    # not turned into an invocation: the selection layer defers to the tool's
    # own schema, so no tool runs and no result is fabricated.
    model = ScriptedLanguageModel(['{"tool": "calculator", "arguments": {}}'])
    tools = FakeToolManager()
    orch = build({ModelRouter: ScriptedRouter(model), ToolManager: tools})

    result = await orch.handle(TOOL_REQUEST_MESSAGE)

    assert tools.calls == []
    assert result.intent.kind == IntentKind.CHAT
    assert result.response == FREE_FORM_REPLY
    assert "42" not in result.response


async def test_no_registered_tools_means_no_decision_call() -> None:
    model = ScriptedLanguageModel([CALCULATOR_DECISION])
    tools = FakeToolManager(tools=[])
    orch = build({ModelRouter: ScriptedRouter(model), ToolManager: tools})

    result = await orch.handle(TOOL_REQUEST_MESSAGE)

    assert model.calls == 1  # ordinary composition only
    assert tools.calls == []
    assert result.intent.kind == IntentKind.CHAT


# -- Auto-selection safety: allowlist and mode gating -------------------------

ECHO = ToolInfo(
    name="echo",
    description="Repeat the given text back.",
    category="utility",
    parameters_schema={
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
)

WRITE_FILE = ToolInfo(
    name="write_file",
    description="Write text content to a file on disk.",
    category="utility",
    parameters_schema={
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"],
    },
)

ALL_TOOLS = [CALCULATOR, CURRENT_TIME, ECHO, WRITE_FILE]


async def test_only_read_only_tools_are_offered_to_the_model() -> None:
    model = ScriptedLanguageModel(['{"tool": null, "arguments": {}}'])
    selector = ModelToolSelector(ScriptedRouter(model), FakeToolManager(tools=ALL_TOOLS))

    await selector.decide(TOOL_REQUEST_MESSAGE)

    request = model.requests[0]
    assert request.response_schema is not None
    assert request.response_schema["properties"]["tool"]["enum"] == [
        "calculator",
        "current_time",
        None,
    ]
    system = request.messages[0].content
    assert "echo" not in system
    assert "write_file" not in system


@pytest.mark.parametrize(
    "decision",
    [
        '{"tool": "echo", "arguments": {"text": "hello"}}',
        '{"tool": "write_file", "arguments": {"path": "a.txt", "content": "x"}}',
    ],
)
async def test_side_effecting_tool_in_decision_is_refused(decision: str) -> None:
    model = ScriptedLanguageModel([decision, FREE_FORM_REPLY])
    tools = FakeToolManager(tools=ALL_TOOLS)
    orch = build({ModelRouter: ScriptedRouter(model), ToolManager: tools})

    result = await orch.handle(TOOL_REQUEST_MESSAGE)

    assert tools.calls == []
    assert result.intent.kind == IntentKind.CHAT
    assert result.response == FREE_FORM_REPLY


@pytest.mark.parametrize(
    "message",
    [
        "can you explain what concrete slump is",
        "write a short note about retention money",
    ],
)
async def test_task_mode_turns_never_consult_tool_selection(message: str) -> None:
    model = ScriptedLanguageModel([FREE_FORM_REPLY])
    tools = FakeToolManager(tools=ALL_TOOLS)
    orch = build({ModelRouter: ScriptedRouter(model), ToolManager: tools})

    result = await orch.handle(message)

    # One ordinary composition call: no decision request, no tool execution.
    assert model.calls == 1
    assert model.requests[0].response_schema is None
    assert tools.calls == []
    assert result.intent.kind == IntentKind.CHAT


async def test_time_question_selects_current_time() -> None:
    model = ScriptedLanguageModel(['{"tool": "current_time", "arguments": {}}'])
    tools = FakeToolManager(tools=ALL_TOOLS)
    orch = build({ModelRouter: ScriptedRouter(model), ToolManager: tools})

    result = await orch.handle("what time is it")

    assert result.intent.kind == IntentKind.TOOL
    assert [name for name, _ in tools.calls] == ["current_time"]
    assert model.calls == 1

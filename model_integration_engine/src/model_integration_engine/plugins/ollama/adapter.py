"""Generic normalized inference adapter for the Ollama chat API."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from ...contracts import (
    InferenceEvent,
    InferenceRequest,
    InferenceResponse,
    MessagePart,
    OperationContext,
    RuntimeDescription,
    ToolCall,
    Usage,
)
from ...domain import JSONValue, PluginDescriptor, SubjectKind, SubjectRef, TrustState
from ...evidence import deterministic_id, sha256_digest
from .client import OllamaClient


class OllamaAdapterError(RuntimeError):
    pass


class OllamaAdapterProtocolError(OllamaAdapterError):
    pass


@dataclass(frozen=True, slots=True)
class OllamaAdapterConfig:
    runtime: SubjectRef
    deployment: SubjectRef
    model_reference: str
    configuration_digest: str
    runtime_owns_template: bool = True

    def __post_init__(self) -> None:
        if not self.model_reference.strip():
            raise ValueError("model_reference must be non-empty")


@dataclass(slots=True)
class GenericOllamaAdapter:
    client: OllamaClient
    config: OllamaAdapterConfig
    descriptor: PluginDescriptor = field(
        default_factory=lambda: PluginDescriptor(
            plugin_id="mie.adapter.ollama-chat",
            plugin_version="0.2.0",
            contract_version="normalized-inference-0.1.0",
            operations=("describe", "infer", "stream", "cancel"),
            supported_subjects=("RUNTIME", "MODEL_DEPLOYMENT"),
            required_permissions=("network:configured-ollama-endpoint",),
            trust_state=TrustState.TRUSTED_EXISTING,
        )
    )
    _cancelled: set[str] = field(default_factory=set, init=False)

    @property
    def adapter_subject(self) -> SubjectRef:
        digest = sha256_digest(
            {
                "plugin_id": self.descriptor.plugin_id,
                "plugin_version": self.descriptor.plugin_version,
                "contract_version": self.descriptor.contract_version,
            }
        )
        return SubjectRef(
            kind=SubjectKind.ADAPTER,
            subject_id="adapter:ollama-chat:generic",
            version=self.descriptor.plugin_version,
            digest=digest,
        )

    async def describe(
        self, deployment: SubjectRef, context: OperationContext
    ) -> RuntimeDescription:
        if deployment.subject_id != self.config.deployment.subject_id:
            raise OllamaAdapterError("Adapter is bound to a different deployment")
        return RuntimeDescription(
            runtime=self.config.runtime,
            deployment=self.config.deployment,
            protocol_version="ollama-native-chat",
            operations=("chat", "stream", "structured_output", "tools"),
            parameters={
                "runtime_owns_template": self.config.runtime_owns_template,
                "model_reference": self.config.model_reference,
            },
            evidence_ids=(),
        )

    def _request_body(self, request: InferenceRequest) -> dict[str, JSONValue]:
        if request.deployment.subject_id != self.config.deployment.subject_id:
            raise OllamaAdapterError("Inference request targets a different deployment")
        if request.operation_id in self._cancelled:
            raise OllamaAdapterError("Inference operation was cancelled")

        messages: list[dict[str, JSONValue]] = []
        if request.system_instruction is not None:
            messages.append({"role": "system", "content": request.system_instruction})

        for message in request.messages:
            text_parts: list[str] = []
            images: list[str] = []
            for part in message.parts:
                if part.kind == "text" and isinstance(part.value, str):
                    text_parts.append(part.value)
                elif part.kind == "image_base64" and isinstance(part.value, str):
                    images.append(part.value)
                else:
                    raise OllamaAdapterError(
                        f"Unsupported normalized message part: {part.kind}"
                    )
            normalized: dict[str, JSONValue] = {
                "role": message.role,
                "content": "".join(text_parts),
            }
            if images:
                normalized["images"] = images
            if message.tool_call_id:
                normalized["tool_call_id"] = message.tool_call_id
            messages.append(normalized)

        body: dict[str, JSONValue] = {
            "model": self.config.model_reference,
            "messages": messages,
        }
        if request.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": dict(tool.input_schema),
                    },
                }
                for tool in request.tools
            ]
        if request.response_schema is not None:
            body["format"] = dict(request.response_schema)
        if request.generation:
            body["options"] = dict(request.generation)
        if request.thinking_preference is not None:
            body["think"] = request.thinking_preference
        if request.maximum_output_tokens is not None:
            options = dict(body.get("options", {}))
            options["num_predict"] = request.maximum_output_tokens
            body["options"] = options
        return body

    async def infer(
        self, request: InferenceRequest, context: OperationContext
    ) -> InferenceResponse:
        events: list[Mapping[str, Any]] = []

        async for raw in self.client.chat_stream(self._request_body(request)):
            if not isinstance(raw, Mapping):
                raise OllamaAdapterProtocolError(
                    "Ollama chat stream event must be an object"
                )
            events.append(raw)

        if not events:
            raise OllamaAdapterProtocolError(
                "Ollama chat stream returned no events"
            )

        content_parts: list[str] = []
        thinking_parts: list[str] = []
        tool_calls: list[Mapping[str, Any]] = []
        terminal = events[-1]

        for raw in events:
            message = raw.get("message")
            if message is not None and not isinstance(message, Mapping):
                raise OllamaAdapterProtocolError(
                    "Ollama chat stream event message must be an object"
                )

            message_map = message if isinstance(message, Mapping) else {}

            content = message_map.get("content", "")
            thinking = message_map.get("thinking", "")

            if not isinstance(content, str) or not isinstance(thinking, str):
                raise OllamaAdapterProtocolError(
                    "Ollama chat stream content/thinking values must be strings"
                )

            content_parts.append(content)
            thinking_parts.append(thinking)

            raw_tool_calls = message_map.get("tool_calls")
            if raw_tool_calls is not None:
                if not isinstance(raw_tool_calls, list):
                    raise OllamaAdapterProtocolError(
                        "message.tool_calls must be an array"
                    )
                tool_calls.extend(
                    item for item in raw_tool_calls
                    if isinstance(item, Mapping)
                )

        terminal_message = terminal.get("message")
        terminal_map = (
            terminal_message
            if isinstance(terminal_message, Mapping)
            else {}
        )

        raw = dict(terminal)
        raw["message"] = {
            "role": (
                terminal_map.get("role")
                if isinstance(terminal_map.get("role"), str)
                else "assistant"
            ),
            "content": "".join(content_parts),
            "thinking": "".join(thinking_parts),
        }

        if tool_calls:
            raw["message"]["tool_calls"] = tool_calls

        return self._parse_response(request.operation_id, raw)

    def _parse_response(
        self, operation_id: str, raw: Mapping[str, Any]
    ) -> InferenceResponse:
        message = raw.get("message")
        if not isinstance(message, Mapping):
            raise OllamaAdapterProtocolError(
                "Ollama chat response requires a message object"
            )

        output_parts: list[MessagePart] = []
        content = message.get("content")
        if content is not None and not isinstance(content, str):
            raise OllamaAdapterProtocolError("message.content must be a string")
        if isinstance(content, str) and content:
            output_parts.append(MessagePart(kind="text", value=content))

        thinking = message.get("thinking")
        if thinking is not None and not isinstance(thinking, str):
            raise OllamaAdapterProtocolError("message.thinking must be a string")
        if isinstance(thinking, str) and thinking:
            output_parts.append(MessagePart(kind="thinking", value=thinking))

        tool_calls = _parse_tool_calls(message.get("tool_calls"))
        warnings = []
        if message.get("images"):
            warnings.append("Response images are preserved only in raw response digest.")

        return InferenceResponse(
            operation_id=operation_id,
            deployment=self.config.deployment,
            output_parts=tuple(output_parts),
            tool_calls=tool_calls,
            finish_reason=raw.get("done_reason")
            if isinstance(raw.get("done_reason"), str)
            else None,
            usage=Usage(
                input_tokens=_optional_int(raw.get("prompt_eval_count")),
                output_tokens=_optional_int(raw.get("eval_count")),
                total_duration_ns=_optional_int(raw.get("total_duration")),
                load_duration_ns=_optional_int(raw.get("load_duration")),
                source="ollama",
            ),
            warnings=tuple(warnings),
            degraded_fields=(),
            raw_response_digest=sha256_digest(raw),
            evidence_ids=(),
        )

    async def stream(
        self, request: InferenceRequest, context: OperationContext
    ) -> AsyncIterator[InferenceEvent]:
        sequence = 0
        async for raw in self.client.chat_stream(self._request_body(request)):
            if not isinstance(raw, Mapping):
                raise OllamaAdapterProtocolError("Stream event must be an object")
            message = raw.get("message")
            if message is not None and not isinstance(message, Mapping):
                raise OllamaAdapterProtocolError(
                    "Stream event message must be an object"
                )
            message_map = message if isinstance(message, Mapping) else {}
            content = message_map.get("content", "")
            thinking = message_map.get("thinking", "")
            if not isinstance(content, str) or not isinstance(thinking, str):
                raise OllamaAdapterProtocolError(
                    "Stream content/thinking values must be strings"
                )
            data: dict[str, JSONValue] = {
                "content": content,
                "thinking": thinking,
                "tool_calls": [
                    {
                        "call_id": item.call_id,
                        "name": item.name,
                        "arguments": dict(item.arguments),
                    }
                    for item in _parse_tool_calls(message_map.get("tool_calls"))
                ],
                "done_reason": raw.get("done_reason")
                if isinstance(raw.get("done_reason"), str)
                else None,
            }
            terminal = raw.get("done") is True
            yield InferenceEvent(
                operation_id=request.operation_id,
                sequence=sequence,
                event_type="done" if terminal else "delta",
                data=data,
                terminal=terminal,
            )
            sequence += 1

    async def cancel(self, operation_id: str, context: OperationContext) -> None:
        self._cancelled.add(operation_id)


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _parse_tool_calls(value: object) -> tuple[ToolCall, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise OllamaAdapterProtocolError("message.tool_calls must be an array")
    calls: list[ToolCall] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            raise OllamaAdapterProtocolError("tool call must be an object")
        function = raw.get("function")
        if not isinstance(function, Mapping):
            raise OllamaAdapterProtocolError("tool call requires function object")
        name = function.get("name")
        arguments = function.get("arguments")
        if not isinstance(name, str) or not isinstance(arguments, Mapping):
            raise OllamaAdapterProtocolError(
                "tool function requires string name and object arguments"
            )
        calls.append(
            ToolCall(
                call_id=raw.get("id") if isinstance(raw.get("id"), str) else None,
                name=name,
                arguments={str(key): value for key, value in arguments.items()},
            )
        )
    return tuple(calls)

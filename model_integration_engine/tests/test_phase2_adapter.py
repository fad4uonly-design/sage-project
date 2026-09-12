from __future__ import annotations

import asyncio

import pytest
from model_integration_engine.contracts import (
    InferenceRequest,
    Message,
    MessagePart,
    ToolDefinition,
)
from model_integration_engine.domain import SubjectKind, SubjectRef
from model_integration_engine.evidence import sha256_digest
from model_integration_engine.plugins.ollama.adapter import (
    GenericOllamaAdapter,
    OllamaAdapterConfig,
    OllamaAdapterProtocolError,
)
from model_integration_engine.plugins.ollama.client import OllamaClient

from tests.phase2_support import FixtureTransport, operation_context

ENDPOINT = "http://fixture-ollama.invalid:11434"
RUNTIME = SubjectRef(SubjectKind.RUNTIME, "runtime:test", digest=sha256_digest("runtime"))
DEPLOYMENT = SubjectRef(
    SubjectKind.DEPLOYMENT, "deployment:test", digest=sha256_digest("deployment")
)


def adapter_for(transport):
    return GenericOllamaAdapter(
        OllamaClient(ENDPOINT, transport),
        OllamaAdapterConfig(
            runtime=RUNTIME,
            deployment=DEPLOYMENT,
            model_reference="example-model:4b",
            configuration_digest=sha256_digest("config"),
        ),
    )


def test_generic_adapter_maps_normalized_request_without_model_branch() -> None:
    transport = FixtureTransport()
    adapter = adapter_for(transport)
    request = InferenceRequest(
        operation_id="adapter-test",
        deployment=DEPLOYMENT,
        messages=(
            Message(
                role="user",
                parts=(MessagePart(kind="text", value="schema-41"),),
            ),
        ),
        tools=(
            ToolDefinition(
                name="echo",
                description="fixture",
                input_schema={"type": "object"},
            ),
        ),
        response_schema={"type": "object"},
        generation={"temperature": 0},
        maximum_output_tokens=32,
    )

    response = asyncio.run(adapter.infer(request, operation_context()))
    body = transport.calls[-1][2]
    assert body["model"] == "example-model:4b"
    assert body["format"] == {"type": "object"}
    assert body["tools"][0]["function"]["name"] == "echo"
    assert body["options"] == {"temperature": 0, "num_predict": 32}
    assert response.deployment == DEPLOYMENT
    assert response.raw_response_digest is not None


def test_generic_adapter_normalizes_stream_events() -> None:
    transport = FixtureTransport()
    adapter = adapter_for(transport)
    request = InferenceRequest(
        operation_id="stream-test",
        deployment=DEPLOYMENT,
        messages=(Message(role="user", parts=(MessagePart("text", "stream"),)),),
    )

    async def collect():
        return [event async for event in adapter.stream(request, operation_context())]

    events = asyncio.run(collect())
    assert [event.sequence for event in events] == [0, 1]
    assert events[-1].terminal is True
    assert "".join(event.data["content"] for event in events) == "MIE_STREAM_OK_62"


def test_malformed_adapter_response_is_explicit() -> None:
    adapter = adapter_for(FixtureTransport(malformed_chat=True))
    request = InferenceRequest(
        operation_id="malformed",
        deployment=DEPLOYMENT,
        messages=(Message(role="user", parts=(MessagePart("text", "hello"),)),),
    )

    with pytest.raises(OllamaAdapterProtocolError):
        asyncio.run(adapter.infer(request, operation_context()))

class _EmptyStreamTransport(FixtureTransport):
    """Streams no events at all (empty NDJSON)."""

    async def stream_ndjson(self, method, url, body, *, timeout_seconds):
        if False:
            yield {}


class _ThinkingStreamTransport(FixtureTransport):
    """Streams interleaved content + thinking chunks (imitates a thinking model)."""

    async def stream_ndjson(self, method, url, body, *, timeout_seconds):
        yield {
            "message": {"role": "assistant", "content": "Hel", "thinking": "Th"},
            "done": False,
        }
        yield {
            "message": {"role": "assistant", "content": "lo", "thinking": "ink"},
            "done": True,
            "done_reason": "stop",
        }


def _request(operation_id: str, prompt: str) -> InferenceRequest:
    return InferenceRequest(
        operation_id=operation_id,
        deployment=DEPLOYMENT,
        messages=(Message(role="user", parts=(MessagePart("text", prompt),)),),
    )


def test_infer_reassembles_streamed_content_chunks() -> None:
    transport = FixtureTransport()
    adapter = adapter_for(transport)
    response = asyncio.run(adapter.infer(_request("reassemble", "hello"), operation_context()))

    # The fixture splits "fixture response" at the midpoint into two stream events.
    body = transport.calls[-1][2]
    assert body["stream"] is True
    assert response.output_parts == (
        MessagePart(kind="text", value="fixture response"),
    )
    assert response.finish_reason == "stop"


def test_infer_joins_marker_stream_segments() -> None:
    adapter = adapter_for(FixtureTransport())
    response = asyncio.run(adapter.infer(_request("marker", "stream"), operation_context()))
    assert "".join(part.value for part in response.output_parts) == "MIE_STREAM_OK_62"


def test_infer_empty_stream_raises_protocol_error() -> None:
    adapter = adapter_for(_EmptyStreamTransport())
    with pytest.raises(OllamaAdapterProtocolError):
        asyncio.run(adapter.infer(_request("empty-stream", "hello"), operation_context()))


def test_infer_forwards_streamed_tool_calls() -> None:
    adapter = adapter_for(FixtureTransport())
    response = asyncio.run(adapter.infer(_request("tool-call", "mie_echo"), operation_context()))
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "mie_echo"
    assert response.tool_calls[0].call_id == "fixture-call-1"


def test_infer_accumulates_thinking_across_chunks() -> None:
    adapter = adapter_for(_ThinkingStreamTransport())
    response = asyncio.run(adapter.infer(_request("thinking", "hello"), operation_context()))
    parts = {part.kind: part.value for part in response.output_parts}
    assert parts["text"] == "Hello"
    assert parts["thinking"] == "Think"

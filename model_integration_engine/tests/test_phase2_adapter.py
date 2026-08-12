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

"""Local model adapter tests."""

from __future__ import annotations

from typing import Any

import httpx
from sage.models.interfaces import CompletionRequest, Message
from sage.models.local._adapter import LocalLanguageModel


class FakeResponse:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return self._data


class FakeAsyncClient:
    last_url: str | None = None
    last_payload: dict[str, Any] | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.timeout = kwargs.get("timeout")

    async def __aenter__(self) -> FakeAsyncClient:
        return self

    async def __aexit__(
        self,
        exc_type: Any,
        exc_value: Any,
        traceback: Any,
    ) -> None:
        pass

    async def post(
        self,
        url: str,
        json: dict[str, Any],
    ) -> FakeResponse:
        FakeAsyncClient.last_url = url
        FakeAsyncClient.last_payload = json

        return FakeResponse(
            {
                "model": "test-local-model",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Hello from the local model.",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 6,
                    "total_tokens": 11,
                },
            }
        )


async def test_local_adapter_complete(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        FakeAsyncClient,
    )

    model = LocalLanguageModel(
        base_url="http://127.0.0.1:11434/v1",
        model_name="test-local-model",
    )

    request = CompletionRequest(
        messages=[
            Message(
                role="system",
                content="You are SAGE.",
            ),
            Message(
                role="user",
                content="Hello.",
            ),
        ],
        temperature=0.3,
        max_tokens=100,
        stop=["END"],
    )

    response = await model.complete(request)

    assert response.content == "Hello from the local model."
    assert response.model == "test-local-model"
    assert response.provider == "local"
    assert response.finish_reason == "stop"

    assert response.usage == {
        "prompt_tokens": 5,
        "completion_tokens": 6,
        "total_tokens": 11,
    }

    assert FakeAsyncClient.last_url == (
        "http://127.0.0.1:11434/v1/chat/completions"
    )

    assert FakeAsyncClient.last_payload == {
        "model": "test-local-model",
        "messages": [
            {
                "role": "system",
                "content": "You are SAGE.",
            },
            {
                "role": "user",
                "content": "Hello.",
            },
        ],
        "temperature": 0.3,
        "max_tokens": 100,
        "stop": ["END"],
    }

async def test_local_adapter_rejects_empty_choices(
    monkeypatch: Any,
) -> None:
    class EmptyChoicesClient(FakeAsyncClient):
        async def post(
            self,
            url: str,
            json: dict[str, Any],
        ) -> FakeResponse:
            return FakeResponse(
                {
                    "model": "test-local-model",
                    "choices": [],
                }
            )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        EmptyChoicesClient,
    )

    model = LocalLanguageModel(
        base_url="http://127.0.0.1:11434/v1",
        model_name="test-local-model",
    )

    request = CompletionRequest(
        messages=[
            Message(
                role="user",
                content="Hello.",
            ),
        ],
    )

    try:
        await model.complete(request)
    except RuntimeError as exc:
        assert str(exc) == "Local model returned no choices."
    else:
        raise AssertionError(
            "Expected RuntimeError for empty choices."
        )


async def test_local_adapter_uses_default_optional_fields(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        FakeAsyncClient,
    )

    model = LocalLanguageModel(
        base_url="http://127.0.0.1:11434/v1/",
        model_name="test-local-model",
    )

    request = CompletionRequest(
        messages=[
            Message(
                role="user",
                content="Hello.",
            ),
        ],
    )

    response = await model.complete(request)

    assert response.content == "Hello from the local model."

    assert FakeAsyncClient.last_url == (
        "http://127.0.0.1:11434/v1/chat/completions"
    )

    assert FakeAsyncClient.last_payload == {
        "model": "test-local-model",
        "messages": [
            {
                "role": "user",
                "content": "Hello.",
            },
        ],
    }


async def test_local_adapter_preserves_http_errors(
    monkeypatch: Any,
) -> None:
    class ErrorResponse:
        def raise_for_status(self) -> None:
            raise httpx.HTTPStatusError(
                "server error",
                request=httpx.Request(
                    "POST",
                    "http://127.0.0.1:11434/v1/chat/completions",
                ),
                response=httpx.Response(
                    500,
                    request=httpx.Request(
                        "POST",
                        "http://127.0.0.1:11434/v1/chat/completions",
                    ),
                ),
            )

        def json(self) -> dict[str, Any]:
            return {}

    class ErrorClient(FakeAsyncClient):
        async def post(
            self,
            url: str,
            json: dict[str, Any],
        ) -> ErrorResponse:
            return ErrorResponse()

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        ErrorClient,
    )

    model = LocalLanguageModel(
        base_url="http://127.0.0.1:11434/v1",
        model_name="test-local-model",
    )

    request = CompletionRequest(
        messages=[
            Message(
                role="user",
                content="Hello.",
            ),
        ],
    )

    try:
        await model.complete(request)
    except httpx.HTTPStatusError:
        pass
    else:
        raise AssertionError(
            "Expected httpx.HTTPStatusError."
        )

def test_local_adapter_extracts_final_answer_after_thinking() -> None:
    from sage.models.local._adapter import _extract_final_content

    content = (
        "<think>"
        "This is internal reasoning."
        "</think>\n\n"
        "Hello from Qwen."
    )

    assert _extract_final_content(content) == "Hello from Qwen."


def test_local_adapter_preserves_normal_content() -> None:
    from sage.models.local._adapter import _extract_final_content

    content = "Hello from the local model."

    assert _extract_final_content(content) == content


def test_local_adapter_handles_empty_content() -> None:
    from sage.models.local._adapter import _extract_final_content

    assert _extract_final_content("") == ""


def test_local_adapter_handles_thinking_without_final_answer() -> None:
    from sage.models.local._adapter import _extract_final_content

    content = "<think>Still thinking..."

    assert _extract_final_content(content) == ""

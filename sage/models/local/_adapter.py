"""Local HTTP language model adapter."""

from __future__ import annotations

from typing import Any

import httpx

from sage.models.interfaces import CompletionRequest, CompletionResponse


def _extract_final_content(content: str) -> str:
    """Extract the final answer from content containing a closing </think> tag."""
    if not content:
        return ""

    closing_tag = "</think>"

    if "<think>" in content and closing_tag not in content:
        return ""

    if closing_tag not in content:
        return content.strip()

    _, final_content = content.split(closing_tag, 1)

    return final_content.strip()


class LocalLanguageModel:
    """Language model adapter for an OpenAI-compatible local HTTP endpoint."""

    def __init__(
        self,
        base_url: str,
        model_name: str,
        timeout: float = 120.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model_name = model_name
        self._timeout = timeout

    @property
    def provider(self) -> str:
        return "local"

    @property
    def model_name(self) -> str:
        return self._model_name

    def build_payload(self, request: CompletionRequest) -> dict[str, Any]:
        """Translate a SAGE request into the endpoint's request payload.

        Free-form calls carry no structured-output constraint; a request that
        asks for a ``response_schema`` gets the provider's constrained-decoding
        parameter instead.
        """
        payload: dict[str, Any] = {
            "model": self._model_name,
            "messages": [
                {
                    "role": message.role,
                    "content": message.content,
                }
                for message in request.messages
            ],
        }

        if request.temperature is not None:
            payload["temperature"] = request.temperature

        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens

        if request.stop is not None:
            payload["stop"] = request.stop

        if request.response_schema is not None:
            # Constrained decoding: Ollama's OpenAI-compatible endpoint accepts
            # the OpenAI ``response_format`` shape and enforces the schema as a
            # grammar underneath (the native /api/chat ``format`` parameter).
            # Callers that request no schema keep free-form generation.
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "sage_response",
                    "schema": request.response_schema,
                },
            }

        return payload

    async def complete(
        self,
        request: CompletionRequest,
    ) -> CompletionResponse:
        payload = self.build_payload(request)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        choices = data.get("choices") or []

        if not choices:
            raise RuntimeError("Local model returned no choices.")

        choice = choices[0]
        message = choice.get("message") or {}
        content = _extract_final_content(message.get("content") or "")

        raw_usage = data.get("usage") or {}

        usage = {
            "prompt_tokens": int(raw_usage.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(
                raw_usage.get("completion_tokens", 0) or 0
            ),
            "total_tokens": int(
                raw_usage.get("total_tokens", 0) or 0
            ),
        }

        return CompletionResponse(
            content=content,
            model=str(data.get("model") or self._model_name),
            provider="local",
            usage=usage,
            raw=data,
            finish_reason=str(choice.get("finish_reason") or "stop"),
        )

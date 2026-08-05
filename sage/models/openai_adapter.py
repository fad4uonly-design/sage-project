"""OpenAI language model adapter (optional dependency)."""

from __future__ import annotations

from typing import Any

from sage.models.interfaces import CompletionRequest, CompletionResponse


class OpenAILanguageModel:
    def __init__(self, api_key: str, model_name: str = "gpt-4o-mini") -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise ImportError(
                "openai package required for OpenAI adapter. Install with: pip install sage[llm]"
            ) from exc

        self._client = AsyncOpenAI(api_key=api_key)
        self._model_name = model_name

    @property
    def provider(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model_name

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        kwargs: dict[str, Any] = {
            "model": self._model_name,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        }
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.max_tokens is not None:
            kwargs["max_tokens"] = request.max_tokens

        resp = await self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        content = choice.message.content or ""
        usage = {}
        if resp.usage:
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens or 0,
                "completion_tokens": resp.usage.completion_tokens or 0,
                "total_tokens": resp.usage.total_tokens or 0,
            }
        return CompletionResponse(
            content=content,
            model=self._model_name,
            provider="openai",
            usage=usage,
            finish_reason=choice.finish_reason or "stop",
        )

"""Anthropic language model adapter (optional dependency)."""

from __future__ import annotations

from typing import Any

from sage.models.interfaces import CompletionRequest, CompletionResponse


class AnthropicLanguageModel:
    def __init__(self, api_key: str, model_name: str = "claude-3-5-sonnet-latest") -> None:
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:
            raise ImportError(
                "anthropic package required. Install with: pip install sage[llm]"
            ) from exc

        self._client = AsyncAnthropic(api_key=api_key)
        self._model_name = model_name

    @property
    def provider(self) -> str:
        return "anthropic"

    @property
    def model_name(self) -> str:
        return self._model_name

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        system_parts = [m.content for m in request.messages if m.role == "system"]
        messages = [
            {"role": m.role, "content": m.content}
            for m in request.messages
            if m.role in ("user", "assistant")
        ]
        kwargs: dict[str, Any] = {
            "model": self._model_name,
            "messages": messages,
            "max_tokens": request.max_tokens or 2048,
        }
        if system_parts:
            kwargs["system"] = "\n\n".join(system_parts)
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature

        resp = await self._client.messages.create(**kwargs)
        content = ""
        for block in resp.content:
            if hasattr(block, "text"):
                content += block.text

        usage = {
            "prompt_tokens": getattr(resp.usage, "input_tokens", 0) or 0,
            "completion_tokens": getattr(resp.usage, "output_tokens", 0) or 0,
        }
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]

        return CompletionResponse(
            content=content,
            model=self._model_name,
            provider="anthropic",
            usage=usage,
            finish_reason=resp.stop_reason or "stop",
        )

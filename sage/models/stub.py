"""Offline stub model — keeps SAGE fully functional without API keys."""

from __future__ import annotations

from collections.abc import Sequence

from sage.models.interfaces import (
    CompletionRequest,
    CompletionResponse,
    EmbeddingModel,
    LanguageModel,
)


class StubLanguageModel:
    """Deterministic offline language model for development and tests."""

    def __init__(self, model_name: str = "stub-v1") -> None:
        self._model_name = model_name

    @property
    def provider(self) -> str:
        return "stub"

    @property
    def model_name(self) -> str:
        return self._model_name

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        user_bits = [m.content for m in request.messages if m.role == "user"]
        last_user = user_bits[-1] if user_bits else ""
        system_bits = [m.content for m in request.messages if m.role == "system"]

        # Lightweight heuristic responses so conversation still feels alive offline
        lower = last_user.lower()
        if any(g in lower for g in ("hello", "hi ", "hey", "good morning", "good evening")):
            text = (
                "Hello. I am SAGE — your Smart Autonomous General Engine. "
                "I am running in offline stub mode, but my memory, planning, and "
                "module architecture are fully active. How can I help you today?"
            )
        elif "remember" in lower or "memory" in lower:
            text = (
                "I store important facts in my Memory System (short-term, long-term, "
                "episodic, semantic, and preferences). Tell me something to remember, "
                "or ask what I already know."
            )
        elif "plan" in lower or "schedule" in lower:
            text = (
                "I can create goals and multi-step plans through the Planning Engine. "
                "Describe an objective and I will outline steps, priorities, and tracking."
            )
        elif system_bits and "reason" in system_bits[0].lower():
            text = (
                f"Reasoning (stub): Given the problem «{last_user}», "
                "I would gather context from memory, enumerate options, "
                "weigh risks, and choose the highest-utility path with an explanation."
            )
        else:
            text = (
                f"[SAGE stub model] I received your message: «{last_user[:400]}». "
                "Connect a real model provider (OpenAI, Anthropic, or a local LLM) "
                "in configuration for full generative capability. "
                "Meanwhile all other SAGE subsystems remain operational."
            )

        return CompletionResponse(
            content=text,
            model=self._model_name,
            provider="stub",
            usage={"prompt_tokens": 0, "completion_tokens": len(text.split()), "total_tokens": 0},
            finish_reason="stop",
        )


class StubEmbeddingModel:
    """Hash-based pseudo-embeddings for offline development (not semantic)."""

    def __init__(self, dims: int = 64) -> None:
        self._dims = dims

    @property
    def provider(self) -> str:
        return "stub"

    @property
    def model_name(self) -> str:
        return f"stub-emb-{self._dims}"

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        result: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self._dims
            for i, ch in enumerate(text.encode("utf-8")):
                vec[i % self._dims] += (ch % 31) / 31.0
            # L2 normalize
            norm = sum(v * v for v in vec) ** 0.5 or 1.0
            result.append([v / norm for v in vec])
        return result


# Type checks for protocols
def _assert_protocols() -> None:
    _: LanguageModel = StubLanguageModel()
    __: EmbeddingModel = StubEmbeddingModel()

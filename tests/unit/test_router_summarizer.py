"""Unit tests for RouterSummarizer — the router-backed ``SummarizeFn``.

No network and no live model: a fake ``LanguageModel`` + fake ``ModelRouter``
stand in for the runtime so we can assert delegation, contract behavior, and the
"no hardcoded provider/model" constraints.
"""

from __future__ import annotations

from inspect import getsource

import pytest

from sage.core import router_summarizer as _rs
from sage.core.router_summarizer import RouterSummarizer
from sage.core.web_learner import (
    DEFAULT_SUMMARIZER,
    WebLearnError,
    WebResult,
)
from sage.models.interfaces import (
    CompletionRequest,
    CompletionResponse,
    ModelRouter,
)

TOPIC = "what is qwen"
RESULTS: list[WebResult] = [
    WebResult(source="https://example.com/qwen", content="Qwen2.5 is a family of LLMs."),
    WebResult(source="https://wiki.example/qwen", content="It supports Chinese and English."),
]
SUMMARY = "Qwen2.5 is a small family of LLMs."


class FakeLanguageModel:
    """Stand-in for a runtime language model (LocalLanguageModel in tests)."""

    provider = "local"
    model_name = "qwen2.5:1.5b"

    def __init__(self, content: str = SUMMARY) -> None:
        self.content = content
        self.complete_calls: list[CompletionRequest] = []

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.complete_calls.append(request)
        return CompletionResponse(
            content=self.content,
            model=self.model_name,
            provider=self.provider,
            usage={},
            raw={},
            finish_reason="stop",
        )


class FakeModelRouter:
    """Records ``get_language_model()`` calls and returns the configured LM."""

    def __init__(self, lm: FakeLanguageModel | None = None) -> None:
        self.lm = lm or FakeLanguageModel()
        self.lang_calls = 0

    def get_language_model(self, *, capability: str | None = None) -> FakeLanguageModel:
        self.lang_calls += 1
        return self.lm

    def get_embedding_model(self):  # not needed for summarization
        return None


def _summarizer(router: FakeModelRouter | None = None) -> RouterSummarizer:
    return RouterSummarizer(router or FakeModelRouter())


async def test_summarize_returns_router_model_content() -> None:
    router = FakeModelRouter()
    summarizer = RouterSummarizer(router)

    out = await summarizer(TOPIC, RESULTS)

    assert out == SUMMARY
    assert router.lang_calls == 1
    assert len(router.lm.complete_calls) == 1
    request = router.lm.complete_calls[0]
    assert len(request.messages) == 2
    assert request.messages[0].role == "system"
    assert request.messages[1].role == "user"
    assert TOPIC in request.messages[1].content
    assert "Qwen2.5 is a family of LLMs." in request.messages[1].content


async def test_is_summarize_fn_contract() -> None:
    """RouterSummarizer is an awaitable callable returning a summary string."""
    out = await _summarizer()(TOPIC, RESULTS)
    assert isinstance(out, str) and out == SUMMARY


def test_does_not_hardcode_ollama_or_model() -> None:
    """Constraints: no Ollama URL, no qwen hard-coding, no second model client."""
    src = getsource(_rs)
    assert "11434" not in src
    assert "qwen2.5" not in src
    assert "LocalLanguageModel(" not in src  # must NOT construct a second client
    assert "StubLanguageModel(" not in src
    assert "http://127" not in src


async def test_model_config_respected_via_router() -> None:
    """The summarizer uses whatever model the router exposes (not a hard-coded one)."""
    lm = FakeLanguageModel()
    router = FakeModelRouter(lm=lm)

    await RouterSummarizer(router)(TOPIC, RESULTS)

    assert router.lang_calls == 1
    assert router.lm is lm  # the exact model the router returned did the work
    assert lm.model_name == "qwen2.5:1.5b"
    assert lm.provider == "local"


async def test_empty_results_returns_empty_string() -> None:
    assert await _summarizer()(TOPIC, []) == ""


async def test_model_failure_raised_as_weblearn_error() -> None:
    class _BoomLM(FakeLanguageModel):
        async def complete(self, request: CompletionRequest) -> CompletionResponse:
            raise RuntimeError("connection refused")

    router = FakeModelRouter(lm=_BoomLM())
    with pytest.raises(WebLearnError, match="connection refused"):
        await RouterSummarizer(router)(TOPIC, RESULTS)


def test_blocked_default_summarizer_unchanged() -> None:
    """RouterSummarizer did not replace the safe never-faking default."""
    from sage.core.web_learner import _BlockedSummarizer

    assert isinstance(DEFAULT_SUMMARIZER, _BlockedSummarizer)

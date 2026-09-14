"""Unit tests for the on-demand WebLearnTool.

The tool is a thin wrapper over the EXISTING WebLearner: it delegates to an
injected learner and returns ToolResults. These tests assert delegation (no
duplicate search/summarize pipeline), metadata/schema, and safe failure modes —
no network, no model.
"""

from __future__ import annotations

from datetime import datetime, timezone
from inspect import getsource

import pytest

from sage.core.web_learner import LearnedSummary, WebLearnError
from sage.tools.base import BaseTool
from sage.tools.interfaces import ToolResult
from sage.tools.builtin.web_learn_tool import WebLearnTool

TOPIC = "what is qwen"
SUMMARY = "Qwen2.5 is a small family of LLMs."
SOURCES = ["https://example.com/qwen", "https://wiki.example/qwen"]


class FakeLearner:
    """Duck-typed WebLearner: records learn() calls, returns a summary."""

    def __init__(self, result: LearnedSummary | None = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error
        self.calls: list[str] = []

    async def learn(self, topic: str) -> LearnedSummary:
        self.calls.append(topic)
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


def _ok_summary(served_from_memory: bool = False) -> LearnedSummary:
    sources = ["memory:mem_1"] if served_from_memory else SOURCES
    return LearnedSummary(
        topic=TOPIC,
        summary=SUMMARY,
        sources=sources,
        learned_at=datetime.now(timezone.utc),
    )


def test_tool_metadata_and_schema() -> None:
    assert WebLearnTool.name == "web_learn"
    assert WebLearnTool.category == "research"
    assert WebLearnTool.parameters_schema["required"] == ["topic"]
    assert "topic" in WebLearnTool.parameters_schema["properties"]
    assert issubclass(WebLearnTool, BaseTool)
    src = getsource(WebLearnTool)
    assert "11434" not in src
    assert "qwen2.5" not in src


@pytest.mark.asyncio
async def test_invokes_weblearner_and_returns_summary() -> None:
    learner = FakeLearner(result=_ok_summary())
    tool = WebLearnTool(learner=learner)

    result = await tool.execute(topic="  " + TOPIC + "  ")

    assert result.success
    assert result.output["topic"] == TOPIC
    assert result.output["summary"] == SUMMARY
    assert result.output["sources"] == SOURCES
    assert learner.calls == [TOPIC]
    assert result.metadata["served_from"] == "web"


@pytest.mark.asyncio
async def test_served_from_memory_is_marked() -> None:
    learner = FakeLearner(result=_ok_summary(served_from_memory=True))
    result = await WebLearnTool(learner=learner).execute(topic=TOPIC)
    assert result.success
    assert result.metadata["served_from"] == "memory"


@pytest.mark.asyncio
async def test_missing_topic_returns_failure() -> None:
    result = await WebLearnTool(learner=FakeLearner()).execute()
    assert not result.success
    assert "topic" in result.error.lower()


@pytest.mark.asyncio
async def test_weblearn_error_mapped_to_failure() -> None:
    learner = FakeLearner(error=WebLearnError("no usable search results"))
    result = await WebLearnTool(learner=learner).execute(topic=TOPIC)
    assert not result.success
    assert "no usable search results" in result.error
    assert result.metadata["kind"] == "learn_error"


@pytest.mark.asyncio
async def test_generic_error_handled_safely() -> None:
    learner = FakeLearner(error=RuntimeError("kaboom"))
    result = await WebLearnTool(learner=learner).execute(topic=TOPIC)
    assert not result.success
    assert "kaboom" in result.error
    assert result.metadata["kind"] == "invoke_error"


@pytest.mark.asyncio
async def test_not_wired_fails_safely_without_crash() -> None:
    # No learner injected -> must NOT raise, must return a clear failure.
    result = await WebLearnTool().execute(topic=TOPIC)
    assert not result.success
    assert result.metadata["kind"] == "not_configured"


def test_no_duplicate_web_learning_pipeline() -> None:
    """The tool must delegate to WebLearner, not implement its own search/summarize."""
    src = getsource(WebLearnTool)
    assert not hasattr(WebLearnTool, "searcher")
    assert not hasattr(WebLearnTool, "summarizer")
    for attr in ("search", "summarize", "_search", "_summarize"):
        assert not hasattr(WebLearnTool, attr)
    assert "learner.learn" in src  # the only path to external knowledge

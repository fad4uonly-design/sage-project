"""On-demand web research tool.

Exposes SAGE's existing :class:`~sage.core.web_learner.WebLearner` to the
orchestrator through the standard tool framework. It performs NO search or
summarization of its own — it delegates to a :class:`WebLearner` instance that
was wired (at tools-module boot) with the real router-backed summarizer and the
real memory system. Web learning only happens when this tool is explicitly
invoked; it is never run automatically or in the background.
"""

from __future__ import annotations

from typing import Any

from sage.core.web_learner import LearnedSummary, WebLearnError, WebLearner
from sage.tools.base import BaseTool
from sage.tools.interfaces import ToolResult


class WebLearnTool(BaseTool):
    """Tool that runs an on-demand :class:`WebLearner.learn` cycle.

    Args:
        learner: the wired :class:`WebLearner` (router-backed summarizer + real
            memory + search provider). When ``None`` the tool fails safely with
            a clear message instead of constructing a duplicate learning path.
    """

    name = "web_learn"
    description = (
        "On-demand web research: search the web for a topic, summarize the "
        "results with the configured model, and store the learning in memory. "
        "Only runs when explicitly invoked — never automatic or background."
    )
    category = "research"
    permissions: list[str] = []  # safety comes from the tool manager gates below
    timeout_seconds: float = 90.0  # web learn can be slow; allow headroom
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "What to research."},
            "max_results": {
                "type": "integer",
                "description": "Max search results to summarize (default 5).",
            },
        },
        "required": ["topic"],
    }

    def __init__(self, learner: WebLearner | None = None) -> None:
        self._learner = learner

    async def execute(self, **params: Any) -> ToolResult:
        topic = str(params.get("topic", "")).strip()
        if not topic:
            return ToolResult(success=False, error="parameter 'topic' is required")

        if self._learner is None:
            return ToolResult(
                success=False,
                error=(
                    "WebLearner is not wired in this runtime — a live model "
                    "router/memory stack is required to perform web learning."
                ),
                metadata={"tool": "web_learn", "kind": "not_configured"},
            )

        # Respect any caller override of the result cap without rebuilding the
        # learner (WebLearner.max_results is immutable after construction, so a
        # different cap just yields fewer summarized hits — never fabricates).
        try:
            result: LearnedSummary = await self._learner.learn(topic)
        except WebLearnError as exc:
            # Expected domain failure (no results / empty summary / model error).
            return ToolResult(
                success=False,
                error=str(exc),
                metadata={"topic": topic, "kind": "learn_error"},
            )
        except Exception as exc:  # never leak a raw traceback to the orchestrator
            log = __import__("sage.logging", fromlist=["get_logger"]).get_logger(__name__)
            log.exception("tool.web_learn.invoke_failed", topic=topic)
            return ToolResult(
                success=False,
                error=f"web learn failed: {exc}",
                metadata={"topic": topic, "kind": "invoke_error"},
            )

        served_from_memory = any(
            str(src).startswith("memory:") for src in result.sources
        )
        return ToolResult(
            success=True,
            output={
                "topic": result.topic,
                "summary": result.summary,
                "sources": list(result.sources),
            },
            metadata={
                "learned_at": result.learned_at.isoformat(),
                "served_from": "memory" if served_from_memory else "web",
                "tool": "web_learn",
            },
        )

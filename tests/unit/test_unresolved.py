"""Residual-unknown marker tests (minimal SAGE-native mechanism).

Covers only the new behavior in ``DefaultOrchestrator._step_retrieve``:

* empty ranked retrieval sets ``ctx["unresolved"]`` with the four keys;
* normal retrieval clears it;
* the marker survives into ``OrchestratorResult.metadata``;
* the marker never enters the TOOL NEXT_TOOL loop path.
"""

from __future__ import annotations

import pytest

from sage.core.engine import SageEngine
from sage.orchestrator.interfaces import Orchestrator
from sage.orchestrator.models import Intent, IntentKind
from sage.retrieval.interfaces import Retriever
from sage.retrieval.models import EvidenceItem, RetrievalLayer, RetrievalResult


class _EmptyRetriever:
    async def retrieve(self, query: str, *, limit: int = 10) -> RetrievalResult:
        return RetrievalResult(query=query, ranked=[])


class _HitRetriever:
    async def retrieve(self, query: str, *, limit: int = 10) -> RetrievalResult:
        ranked = [
            EvidenceItem(
                layer=RetrievalLayer.MEMORY,
                content="User waters orchids on Fridays",
                score=0.9,
                confidence=0.8,
                source_ref="memory-id-1",
            )
        ]
        return RetrievalResult(query=query, ranked=ranked)


def _chat_intent(message: str) -> Intent:
    return Intent(
        kind=IntentKind.CHAT,
        confidence=0.5,
        subject=message,
        raw_message=message,
    )


@pytest.mark.asyncio
async def test_empty_retrieval_creates_unresolved(engine: SageEngine) -> None:
    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]
    engine.container.register_instance(Retriever, _EmptyRetriever())
    ctx: dict = {}
    await orch._step_retrieve(_chat_intent("obscure topic"), "obscure topic", ctx)  # noqa: SLF001
    unresolved = ctx.get("unresolved")
    assert unresolved == {
        "unresolved": True,
        "reason": "no_evidence",
        "missing": ["retrieval evidence"],
        "bounded_next_warranted": False,
    }


@pytest.mark.asyncio
async def test_normal_retrieval_does_not_create_unresolved(engine: SageEngine) -> None:
    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]
    engine.container.register_instance(Retriever, _HitRetriever())
    ctx: dict = {"unresolved": {"unresolved": True}}
    await orch._step_retrieve(_chat_intent("orchids"), "orchids", ctx)  # noqa: SLF001
    assert "unresolved" not in ctx


@pytest.mark.asyncio
async def test_unresolved_survives_into_result_metadata(engine: SageEngine) -> None:
    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]
    engine.container.register_instance(Retriever, _EmptyRetriever())
    result = await orch.handle("tell me about zqxj unmapped topic")
    assert result.metadata.get("unresolved") == {
        "unresolved": True,
        "reason": "no_evidence",
        "missing": ["retrieval evidence"],
        "bounded_next_warranted": False,
    }


@pytest.mark.asyncio
async def test_unresolved_does_not_trigger_tool_loop(engine: SageEngine) -> None:
    from sage.tools.interfaces import ToolManager

    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]
    engine.container.register_instance(Retriever, _EmptyRetriever())
    tools = engine.container.resolve(ToolManager)  # type: ignore[type-abstract]
    calls: list[tuple[str, dict]] = []
    inner = tools.invoke

    async def _spy(name: str, **params):  # type: ignore[no-untyped-def]
        calls.append((name, params))
        return await inner(name, **params)

    tools.invoke = _spy  # type: ignore[method-assign]
    result = await orch.handle("tell me about zqxj unmapped topic")
    assert calls == []
    assert result.metadata.get("unresolved", {}).get("unresolved") is True
    assert result.intent.kind != IntentKind.TOOL


@pytest.mark.asyncio
async def test_fallback_without_retriever_recomputes_stale_unresolved() -> None:
    """The no-Retriever fallback branch recomputes the marker from the
    evidence it actually produced: a stale marker is replaced (not silently
    preserved) and the canonical no-evidence state is set."""
    from sage.core.container import Container
    from sage.orchestrator.engine import DefaultOrchestrator

    orch = DefaultOrchestrator(Container())
    ctx: dict = {"unresolved": {"unresolved": True, "reason": "stale"}}
    outcome = await orch._step_retrieve(_chat_intent("obscure topic"), "obscure topic", ctx)  # noqa: SLF001
    assert outcome == "retrieve=fallback"
    assert ctx["unresolved"] == {
        "unresolved": True,
        "reason": "no_evidence",
        "missing": ["retrieval evidence"],
        "bounded_next_warranted": False,
    }


@pytest.mark.asyncio
async def test_fallback_with_evidence_clears_stale_unresolved() -> None:
    """When the fallback's memory leg finds evidence, the recomputation
    clears a stale marker -- mirroring the ranked-path clear guarantee."""
    from types import SimpleNamespace

    from sage.core.container import Container
    from sage.memory.interfaces import MemorySystem
    from sage.orchestrator.engine import DefaultOrchestrator

    class _Memory:
        async def recall(self, query: str, *, limit: int = 10):
            return [SimpleNamespace(content="User waters orchids on Fridays")]

    container = Container()
    container.register_instance(MemorySystem, _Memory())
    orch = DefaultOrchestrator(container)
    ctx: dict = {"unresolved": {"unresolved": True, "reason": "stale"}}
    await orch._step_retrieve(_chat_intent("orchids"), "orchids", ctx)  # noqa: SLF001
    assert "unresolved" not in ctx
    assert ctx["memories"] == ["User waters orchids on Fridays"]

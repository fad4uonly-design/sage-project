"""Orchestrator tests."""

from __future__ import annotations

from typing import Any

import pytest

from sage.core.engine import SageEngine
from sage.models.interfaces import CompletionResponse
from sage.orchestrator.interfaces import Orchestrator
from sage.orchestrator.models import IntentKind


@pytest.mark.asyncio
async def test_intent_remember(engine: SageEngine) -> None:
    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]
    intent = await orch.analyze_intent("remember: water the tomatoes daily")
    assert intent.kind == IntentKind.REMEMBER
    assert "tomatoes" in intent.subject.lower()


@pytest.mark.asyncio
async def test_handle_remember_recall(engine: SageEngine) -> None:
    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]
    r1 = await orch.handle("remember: SAGE orchestrator routes all cognition")
    assert "remember" in r1.response.lower() or "orchestrator" in r1.response.lower()
    assert r1.intent.kind == IntentKind.REMEMBER
    assert r1.steps

    r2 = await orch.handle("what do you remember about orchestrator")
    assert "orchestrator" in r2.response.lower()
    assert r2.intent.kind == IntentKind.RECALL


@pytest.mark.asyncio
async def test_handle_plan(engine: SageEngine) -> None:
    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]
    # Generic plan (no domain keywords) stays on planning path
    result = await orch.handle("plan a weekly study schedule for calculus")
    assert result.intent.kind in {IntentKind.PLAN, IntentKind.AGENT}
    assert "step" in result.response.lower() or "1." in result.response or "plan" in result.response.lower()


@pytest.mark.asyncio
async def test_handle_agriculture_agent(engine: SageEngine) -> None:
    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]
    result = await orch.handle("Create irrigation plan for tomatoes in summer heat")
    assert result.intent.kind == IntentKind.AGENT
    assert result.intent.entities.get("domain") == "agriculture"
    assert "irrigation" in result.response.lower() or "water" in result.response.lower()

class _CaptureLanguageModel:
    provider = "test"
    model_name = "test-model"

    def __init__(self) -> None:
        self.request: Any = None

    async def complete(self, request: Any) -> CompletionResponse:
        self.request = request
        return CompletionResponse(
            content="captured",
            model=self.model_name,
            provider=self.provider,
            usage={
                "prompt_tokens": 101,
                "completion_tokens": 17,
                "total_tokens": 118,
            },
            raw={},
            finish_reason="stop",
        )


class _CaptureModelRouter:
    def __init__(self) -> None:
        self.language_model = _CaptureLanguageModel()

    def get_language_model(self, *, capability: str | None = None) -> _CaptureLanguageModel:
        return self.language_model

    def get_embedding_model(self) -> None:
        return None


@pytest.mark.asyncio
async def test_chat_memory_context_is_explicitly_grounded(engine: SageEngine) -> None:
    from sage.models.interfaces import ModelRouter
    from sage.orchestrator.models import Intent

    router = _CaptureModelRouter()
    engine.container.register_instance(ModelRouter, router)

    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]

    intent = Intent(
        kind=IntentKind.CHAT,
        confidence=1.0,
        raw_message="What do you know about me?",
    )
    ctx = {
        "history": [],
        "memories": ["SAGE should remain simple and user-controlled."],
    }

    response = await orch._step_compose(
        intent,
        "What do you know about me?",
        ctx,
    )

    assert response == "captured"
    assert router.language_model.request is not None
    assert ctx["_model_usage"] == [
        {
            "stage": "compose",
            "provider": "test",
            "model": "test-model",
            "prompt_tokens": 101,
            "completion_tokens": 17,
            "total_tokens": 118,
        }
    ]

    system_prompt = router.language_model.request.messages[0].content
    assert "SAGE should remain simple and user-controlled." in system_prompt
    assert "Use provided memories and knowledge as evidence." in system_prompt
    assert "do not present unsupported assumptions or invented personal facts as known facts" in system_prompt
    assert "clearly indicate that it is an inference" in system_prompt

@pytest.mark.asyncio
async def test_compose_prefers_ranked_evidence_with_provenance(engine: SageEngine) -> None:
    """Provenance preservation: ranked EvidenceItems render with layer,
    confidence and source, and the same content is not duplicated by the
    legacy flattened string lists."""
    from sage.models.interfaces import ModelRouter
    from sage.orchestrator.models import Intent
    from sage.retrieval.models import EvidenceItem, RetrievalLayer, RetrievalResult

    router = _CaptureModelRouter()
    engine.container.register_instance(ModelRouter, router)

    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]

    item = EvidenceItem(
        layer=RetrievalLayer.MEMORY,
        content="SAGE should remain simple and user-controlled.",
        score=0.95,
        confidence=0.90,
        source_ref="memory-id-1",
        metadata={"source": "memory-id-1"},
    )
    retrieval = RetrievalResult(
        query="What do you know about me?",
        ranked=[item],
        memories=["SAGE should remain simple and user-controlled."],
        overall_confidence=0.90,
    )

    intent = Intent(
        kind=IntentKind.CHAT,
        confidence=1.0,
        raw_message="What do you know about me?",
    )
    ctx = {
        "history": [],
        "memories": ["SAGE should remain simple and user-controlled."],
        "retrieval": retrieval,
        "retrieval_confidence": 0.90,
    }

    response = await orch._step_compose(
        intent,
        "What do you know about me?",
        ctx,
    )

    assert response == "captured"
    assert router.language_model.request is not None
    system_prompt = router.language_model.request.messages[0].content

    # Evidence content AND provenance survive into the composition boundary.
    assert "SAGE should remain simple and user-controlled." in system_prompt
    assert "[memory | confidence 0.90]" in system_prompt
    assert "source: memory-id-1" in system_prompt
    # Raw retrieval relevance must never leak as evidence confidence.
    assert "0.95" not in system_prompt
    # No duplicate: the same memory appears once, not in both blocks.
    assert system_prompt.count("SAGE should remain simple and user-controlled.") == 1


@pytest.mark.asyncio
async def test_compose_without_retrieval_keeps_legacy_strings(engine: SageEngine) -> None:
    """Existing string-based context behavior is unchanged when no
    RetrievalResult is present."""
    from sage.models.interfaces import ModelRouter
    from sage.orchestrator.models import Intent

    router = _CaptureModelRouter()
    engine.container.register_instance(ModelRouter, router)

    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]

    intent = Intent(
        kind=IntentKind.CHAT,
        confidence=1.0,
        raw_message="What do you know about me?",
    )
    ctx = {
        "history": [],
        "memories": ["SAGE should remain simple and user-controlled."],
    }

    response = await orch._step_compose(
        intent,
        "What do you know about me?",
        ctx,
    )

    assert response == "captured"
    assert router.language_model.request is not None
    system_prompt = router.language_model.request.messages[0].content
    assert "SAGE should remain simple and user-controlled." in system_prompt
    assert "You've said:" in system_prompt


def test_evidence_block_renderer_unit() -> None:
    """evidence_block() renders content + provenance, skips empties, caps."""
    from sage.conversation.personality import evidence_block
    from sage.retrieval.models import EvidenceItem, RetrievalLayer

    assert evidence_block([]) is None
    assert evidence_block(None) is None  # type: ignore[arg-type]

    block = evidence_block(
        [
            EvidenceItem(
                layer=RetrievalLayer.MEMORY,
                content="Fact one.",
                confidence=0.9,
                source_ref="mem-1",
            ),
            EvidenceItem(
                layer=RetrievalLayer.DOCUMENT,
                content="Doc one.",
                confidence=0.78,
                source_ref="doc-9",
            ),
            EvidenceItem(layer=RetrievalLayer.PATTERN, content="   ", confidence=0.5),
        ]
    )
    assert block is not None
    assert "Fact one." in block and "mem-1" in block
    assert "Doc one." in block and "doc-9" in block
    assert "[memory | confidence 0.90]" in block
    assert "[document | confidence 0.78]" in block


def _retrieval_with_ranked(ranked: list) -> Any:
    """Build a RetrievalResult carrying the given ranked evidence items."""
    from sage.retrieval.models import RetrievalResult

    return RetrievalResult(query="q", ranked=ranked)


class _StubRetriever:
    """Retriever double returning a fixed RetrievalResult."""

    def __init__(self, result: Any) -> None:
        self._result = result

    async def retrieve(self, query: str, *, limit: int = 10) -> Any:
        return self._result


@pytest.mark.asyncio
async def test_result_metadata_exposes_evidence_provenance(engine: SageEngine) -> None:
    """Ranked evidence appears in OrchestratorResult.metadata with exactly
    layer/confidence/source_ref — raw score is never exposed."""
    from sage.models.interfaces import ModelRouter
    from sage.retrieval.interfaces import Retriever
    from sage.retrieval.models import EvidenceItem, RetrievalLayer

    retrieval = _retrieval_with_ranked(
        [
            EvidenceItem(
                layer=RetrievalLayer.MEMORY,
                content="Proven fact.",
                score=0.99,
                confidence=0.9,
                source_ref="memory-id-1",
                metadata={"source": "user"},
            ),
            EvidenceItem(
                layer=RetrievalLayer.DOCUMENT,
                content="Documented fact.",
                score=0.70,
                confidence=0.78,
                source_ref="doc-9",
            ),
        ]
    )
    engine.container.register_instance(Retriever, _StubRetriever(retrieval))
    engine.container.register_instance(ModelRouter, _CaptureModelRouter())

    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]
    result = await orch.handle("What do you know about me?")

    provenance = result.metadata["evidence_provenance"]
    assert provenance == [
        {"layer": "memory", "confidence": 0.9, "source_ref": "memory-id-1"},
        {"layer": "document", "confidence": 0.78, "source_ref": "doc-9"},
    ]


@pytest.mark.asyncio
async def test_result_metadata_provenance_caps_at_eight(engine: SageEngine) -> None:
    """Only the first 8 ranked items are exposed in metadata."""
    from sage.models.interfaces import ModelRouter
    from sage.retrieval.interfaces import Retriever
    from sage.retrieval.models import EvidenceItem, RetrievalLayer

    ranked = [
        EvidenceItem(
            layer=RetrievalLayer.MEMORY,
            content=f"Fact {i}.",
            score=1.0 - i * 0.01,
            confidence=0.9,
            source_ref=f"mem-{i}",
        )
        for i in range(10)
    ]
    engine.container.register_instance(
        Retriever, _StubRetriever(_retrieval_with_ranked(ranked))
    )
    engine.container.register_instance(ModelRouter, _CaptureModelRouter())

    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]
    result = await orch.handle("What do you know about me?")

    provenance = result.metadata["evidence_provenance"]
    assert len(provenance) == 8
    assert [p["source_ref"] for p in provenance] == [f"mem-{i}" for i in range(8)]


@pytest.mark.asyncio
async def test_result_metadata_provenance_empty_without_retrieval(
    engine: SageEngine,
) -> None:
    """A turn with no retrieval result stays safe: empty provenance list."""
    orch = engine.container.resolve(Orchestrator)  # type: ignore[type-abstract]
    result = await orch.handle("hi bro")

    assert result.metadata["evidence_provenance"] == []

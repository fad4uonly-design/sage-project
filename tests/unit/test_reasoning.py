"""Reasoning engine tests."""

from __future__ import annotations

from typing import Any

import pytest
from sage.core.engine import SageEngine
from sage.models.interfaces import CompletionResponse
from sage.reasoning.interfaces import ReasoningEngine
from sage.reasoning.models import ReasoningContext, StrategyKind


@pytest.mark.asyncio
async def test_reason_returns_trace(engine: SageEngine) -> None:
    re_ = engine.container.resolve(ReasoningEngine)  # type: ignore[type-abstract]
    result = await re_.reason(
        "Should I expand the farm this season?",
        context=ReasoningContext(facts=["Budget is limited", "Soil tests are good"]),
    )
    assert result.conclusion
    assert len(result.trace) >= 2
    assert result.strategy in StrategyKind


@pytest.mark.asyncio
async def test_decision_strategy(engine: SageEngine) -> None:
    re_ = engine.container.resolve(ReasoningEngine)  # type: ignore[type-abstract]
    result = await re_.reason("Should I choose option A or B?", strategy=StrategyKind.DECISION)
    assert result.strategy == StrategyKind.DECISION
    assert result.alternatives


# -- Provenance propagation (recording model seam, mirrors test_orchestrator) --


class _RecordingLanguageModel:
    provider = "recording"
    model_name = "recording-v1"

    def __init__(self) -> None:
        self.requests: list[Any] = []

    async def complete(self, request: Any) -> CompletionResponse:
        self.requests.append(request)
        return CompletionResponse(
            content="Recorded conclusion.",
            model=self.model_name,
            provider=self.provider,
            usage={},
            raw={},
            finish_reason="stop",
        )


class _RecordingModelRouter:
    def __init__(self) -> None:
        self.language_model = _RecordingLanguageModel()

    def get_language_model(
        self, *, capability: str | None = None
    ) -> _RecordingLanguageModel:
        return self.language_model

    def get_embedding_model(self) -> None:
        return None


class _StubRetriever:
    """Retriever double returning a fixed RetrievalResult."""

    def __init__(self, result: Any) -> None:
        self._result = result

    async def retrieve(self, query: str, *, limit: int = 10) -> Any:
        return self._result


@pytest.mark.asyncio
async def test_model_assist_sends_evidence_provenance_to_prompt() -> None:
    """Supplied evidence_provenance reaches the model prompt with layer,
    confidence and source_ref; the raw retrieval score never appears."""
    from sage.reasoning.engine import DefaultReasoningEngine

    router = _RecordingModelRouter()
    re_ = DefaultReasoningEngine(models=router)
    ctx = ReasoningContext(
        memories=["SAGE should remain simple and user-controlled."],
        metadata={
            "evidence_provenance": [
                {"layer": "memory", "confidence": 0.9, "source_ref": "memory-id-1"},
            ]
        },
    )

    result = await re_.reason(
        "Why keep SAGE simple?", context=ctx, use_retrieval=False
    )

    assert router.language_model.requests, "model assist should call the model"
    user_prompt = router.language_model.requests[-1].messages[-1].content
    assert "Memories:" in user_prompt
    assert "SAGE should remain simple and user-controlled." in user_prompt
    assert "Evidence provenance:" in user_prompt
    assert "[memory | confidence 0.90]" in user_prompt
    assert "source: memory-id-1" in user_prompt
    assert "score" not in user_prompt
    assert result.conclusion == "Recorded conclusion."


@pytest.mark.asyncio
async def test_enrich_from_retrieval_carries_evidence_provenance(
    engine: SageEngine,
) -> None:
    """_enrich_from_retrieval preserves prior metadata and derives provenance
    from the ranked evidence (layer / confidence / source_ref only)."""
    from sage.reasoning.engine import DefaultReasoningEngine
    from sage.retrieval.interfaces import Retriever
    from sage.retrieval.models import EvidenceItem, RetrievalLayer, RetrievalResult

    ranked = [
        EvidenceItem(
            layer=RetrievalLayer.MEMORY,
            content="Proven fact.",
            score=0.99,
            confidence=0.9,
            source_ref="memory-id-1",
        ),
        EvidenceItem(
            layer=RetrievalLayer.DOCUMENT,
            content="Doc fact.",
            score=0.8,
            confidence=0.7,
            source_ref="doc-9",
        ),
    ]
    engine.container.register_instance(
        Retriever, _StubRetriever(RetrievalResult(query="q", ranked=ranked))
    )

    re_ = DefaultReasoningEngine(container=engine.container)
    enriched = await re_._enrich_from_retrieval("q", ReasoningContext())

    provenance = enriched.metadata["evidence_provenance"]
    assert provenance[0] == {
        "layer": "memory",
        "confidence": 0.9,
        "source_ref": "memory-id-1",
    }
    assert provenance[1]["layer"] == "document"
    assert provenance[1]["source_ref"] == "doc-9"
    assert all("score" not in item for item in provenance)

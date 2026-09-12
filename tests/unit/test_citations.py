"""Citation extraction and formatting tests (RAGforge)."""

from __future__ import annotations

import pytest
from sage.core.engine import SageEngine
from sage.memory.interfaces import MemorySystem
from sage.memory.models import MemoryItem, MemoryType
from sage.retrieval.citations import (
    LOW_CONFIDENCE_THRESHOLD,
    build_citations,
    format_citations,
    format_citations_for_prompt,
    low_confidence_citations,
)
from sage.retrieval.interfaces import Retriever
from sage.retrieval.models import Citation, EvidenceItem, RetrievalLayer, RetrievalResult


def _item(
    content: str = "alpha",
    layer: RetrievalLayer = RetrievalLayer.MEMORY,
    confidence: float = 0.82,
    source_ref: str | None = "mem_1",
) -> EvidenceItem:
    return EvidenceItem(layer=layer, content=content, confidence=confidence, source_ref=source_ref)


class TestBuildCitations:
    def test_empty_ranked_list(self) -> None:
        assert build_citations([]) == []

    def test_one_indexed_preserving_rank_order(self) -> None:
        ranked = [_item("first"), _item("second"), _item("third")]
        citations = build_citations(ranked)
        assert [c.index for c in citations] == [1, 2, 3]
        assert [c.content for c in citations] == ["first", "second", "third"]

    def test_fields_copied_from_evidence(self) -> None:
        ranked = [_item("fact", RetrievalLayer.DOCUMENT, 0.91, "doc_7")]
        (citation,) = build_citations(ranked)
        assert citation.layer == RetrievalLayer.DOCUMENT
        assert citation.content == "fact"
        assert citation.confidence == 0.91
        assert citation.source_ref == "doc_7"

    def test_confidence_rounded_to_three_decimals(self) -> None:
        (citation,) = build_citations([_item(confidence=0.123456)])
        assert citation.confidence == 0.123

    def test_none_source_ref_passthrough(self) -> None:
        (citation,) = build_citations([_item(source_ref=None)])
        assert citation.source_ref is None


class TestRetrievalResultCitations:
    def test_citations_default_empty(self) -> None:
        result = RetrievalResult(query="q")
        assert result.citations == []


class TestFormatCitations:
    def test_empty_returns_empty_string(self) -> None:
        result = RetrievalResult(query="q")
        assert format_citations(result) == ""

    def test_human_readable_block(self) -> None:
        result = RetrievalResult(
            query="q",
            citations=[Citation(index=1, layer=RetrievalLayer.MEMORY, content="alpha", confidence=0.82)],
        )
        assert format_citations(result) == "[1] (memory, confidence 0.82) alpha"


class TestFormatCitationsForPrompt:
    def test_no_evidence_branch(self) -> None:
        result = RetrievalResult(query="q")
        assert "No retrieved evidence is available" in format_citations_for_prompt(result)

    def test_populated_prompt_instructs_citing(self) -> None:
        result = RetrievalResult(
            query="q",
            citations=[Citation(index=1, layer=RetrievalLayer.MEMORY, content="alpha", confidence=0.82)],
        )
        prompt = format_citations_for_prompt(result)
        assert "[1]" in prompt
        assert "cite sources by their [n] numbers" in prompt


class TestLowConfidenceCitations:
    def test_flags_only_below_threshold(self) -> None:
        low = Citation(index=1, layer=RetrievalLayer.MEMORY, content="weak", confidence=LOW_CONFIDENCE_THRESHOLD - 0.05)
        high = Citation(index=2, layer=RetrievalLayer.DOCUMENT, content="strong", confidence=0.9)
        result = RetrievalResult(query="q", citations=[low, high])
        assert low_confidence_citations(result) == [low]

    def test_boundary_confidence_not_flagged(self) -> None:
        at = Citation(index=1, layer=RetrievalLayer.MEMORY, content="edge", confidence=LOW_CONFIDENCE_THRESHOLD)
        result = RetrievalResult(query="q", citations=[at])
        assert low_confidence_citations(result) == []


def test_package_exports_citation_helpers() -> None:
    import sage.retrieval as r

    for name in ("build_citations", "format_citations", "format_citations_for_prompt", "low_confidence_citations"):
        assert hasattr(r, name)
        assert name in r.__all__


@pytest.mark.asyncio
async def test_pipeline_populates_citations(engine: SageEngine) -> None:
    mem = engine.container.resolve(MemorySystem)  # type: ignore[type-abstract]
    await mem.store(
        MemoryItem(
            type=MemoryType.FACT,
            content="User irrigates tomatoes every morning",
            importance=0.8,
            source="test",
        )
    )
    retriever = engine.container.resolve(Retriever)  # type: ignore[type-abstract]
    result = await retriever.retrieve("tomatoes irrigation", limit=10)
    assert result.citations
    first = result.citations[0]
    assert first.index == 1
    assert first.content == result.ranked[0].content
    assert first.confidence == pytest.approx(result.ranked[0].confidence, abs=1e-3)
    assert {c.layer for c in result.citations} <= set(RetrievalLayer)

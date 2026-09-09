"""RAGforge — surface per-layer confidence as citations.

The retrieval pipeline already scores every evidence item with a confidence.
Citations make that confidence visible to the answer layer and the user: each
cited source carries its retrieval layer, its confidence, and a stable [n]
index so answers can reference evidence explicitly instead of paraphrasing it
silently.
"""

from __future__ import annotations

from sage.retrieval.models import Citation, EvidenceItem, RetrievalResult

# Below this confidence a citation is flagged so the answer layer can hedge.
LOW_CONFIDENCE_THRESHOLD = 0.6


def build_citations(ranked: list[EvidenceItem]) -> list[Citation]:
    """Turn ranked evidence into 1-indexed citations preserving rank order."""
    return [
        Citation(
            index=position,
            layer=item.layer,
            content=item.content,
            confidence=round(float(item.confidence), 3),
            source_ref=item.source_ref,
        )
        for position, item in enumerate(ranked, start=1)
    ]


def format_citations(result: RetrievalResult) -> str:
    """Human-readable citation block, e.g. ``[1] (memory, 0.82) content``."""
    if not result.citations:
        return ""
    lines = [
        f"[{c.index}] ({c.layer.value}, confidence {c.confidence:.2f}) {c.content}"
        for c in result.citations
    ]
    return "\n".join(lines)


def format_citations_for_prompt(result: RetrievalResult) -> str:
    """Citation block plus instructions for a grounded, model-facing prompt."""
    block = format_citations(result)
    if not block:
        return "No retrieved evidence is available. Answer from general knowledge and say that no sources were found."
    return (
        "Retrieved evidence with per-source confidence:\n"
        f"{block}\n\n"
        "Answer using this evidence and cite sources by their [n] numbers. "
        f"Flag any citation with confidence below {LOW_CONFIDENCE_THRESHOLD:.2f} as uncertain. "
        "If the evidence does not contain the answer, say so instead of guessing."
    )


def low_confidence_citations(result: RetrievalResult) -> list[Citation]:
    """Citations whose confidence is below the hedging threshold."""
    return [c for c in result.citations if c.confidence < LOW_CONFIDENCE_THRESHOLD]

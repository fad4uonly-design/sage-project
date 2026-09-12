"""Layered retrieval intelligence."""

from sage.retrieval.citations import (
    build_citations,
    format_citations,
    format_citations_for_prompt,
    low_confidence_citations,
)
from sage.retrieval.interfaces import Retriever
from sage.retrieval.pipeline import LayeredRetriever
from sage.retrieval.service import RetrievalModule

__all__ = [
    "LayeredRetriever",
    "RetrievalModule",
    "Retriever",
    "build_citations",
    "format_citations",
    "format_citations_for_prompt",
    "low_confidence_citations",
]

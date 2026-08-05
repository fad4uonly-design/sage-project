"""Retriever protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from sage.retrieval.models import RetrievalResult


@runtime_checkable
class Retriever(Protocol):
    async def retrieve(self, query: str, *, limit: int = 10) -> RetrievalResult: ...

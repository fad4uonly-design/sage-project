"""Knowledge manager protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from sage.knowledge.models import DocumentRef, KnowledgeHit


@runtime_checkable
class KnowledgeManager(Protocol):
    async def ingest(self, path: Path | str, *, category: str | None = None) -> DocumentRef: ...

    async def search(self, query: str, *, limit: int = 10) -> list[KnowledgeHit]: ...

    async def summarize(self, document_id: str) -> str: ...

    async def categorize(self, document_id: str) -> list[str]: ...

    async def relate(self, source_id: str, target_id: str, relation: str) -> None: ...

    async def get(self, document_id: str) -> DocumentRef | None: ...

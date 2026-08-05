"""Knowledge graph protocol."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from sage.knowledge.graph.models import (
    Entity,
    EntityType,
    ExtractionResult,
    GraphEdge,
    GraphPath,
    GraphTriple,
)


@runtime_checkable
class KnowledgeGraph(Protocol):
    async def upsert_entity(self, entity: Entity) -> Entity: ...

    async def get_entity(self, entity_id: str) -> Entity | None: ...

    async def find_entity(self, name: str, *, entity_type: EntityType | None = None) -> Entity | None: ...

    async def search_entities(self, query: str, *, limit: int = 20) -> list[Entity]: ...

    async def link(
        self,
        source: str | Entity,
        relation: str,
        target: str | Entity,
        *,
        confidence: float = 0.5,
        weight: float = 1.0,
        bidirectional: bool | None = None,
        source_ref: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> GraphEdge: ...

    async def neighbors(
        self,
        entity_id: str,
        *,
        relation: str | None = None,
        direction: str = "both",
        limit: int = 50,
    ) -> list[GraphTriple]: ...

    async def path(
        self,
        source_id: str,
        target_id: str,
        *,
        max_depth: int = 4,
    ) -> GraphPath | None: ...

    async def query_relation(
        self,
        subject: str | None = None,
        relation: str | None = None,
        obj: str | None = None,
        *,
        limit: int = 50,
    ) -> list[GraphTriple]: ...

    async def extract_and_merge(
        self,
        text: str,
        *,
        source: str = "extraction",
        source_ref: str | None = None,
        document_id: str | None = None,
        chunk_id: str | None = None,
        memory_id: str | None = None,
    ) -> ExtractionResult: ...

    async def subgraph(self, seed_ids: Sequence[str], *, depth: int = 1) -> list[GraphTriple]: ...

    async def stats(self) -> dict[str, Any]: ...

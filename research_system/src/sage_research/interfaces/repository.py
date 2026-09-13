"""Knowledge repository boundary (persistence port)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..domain.knowledge import KnowledgeLayer, KnowledgeRecord


class KnowledgeRepository(ABC):
    """Stores and retrieves :class:`KnowledgeRecord` objects.

    Implementations may be in-memory, JSON-file-backed, or a database. The
    research layer depends only on this port.
    """

    @abstractmethod
    def save(self, record: KnowledgeRecord) -> None:
        """Persist (upsert) a record keyed by ``knowledge_id``."""
        raise NotImplementedError

    @abstractmethod
    def get(self, knowledge_id: str) -> KnowledgeRecord | None:
        """Return the record with ``knowledge_id`` or ``None``."""
        raise NotImplementedError

    @abstractmethod
    def all_records(self) -> tuple[KnowledgeRecord, ...]:
        """Return all stored records (deterministic order preferred)."""
        raise NotImplementedError

    @abstractmethod
    def find(
        self,
        *,
        subject: str | None = None,
        layer: KnowledgeLayer | None = None,
    ) -> tuple[KnowledgeRecord, ...]:
        """Return records matching the given filters."""
        raise NotImplementedError

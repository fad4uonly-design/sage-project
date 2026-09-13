"""In-memory knowledge repository (default for tests and interactive use)."""

from __future__ import annotations

from ..domain.knowledge import KnowledgeLayer, KnowledgeRecord
from ..interfaces.repository import KnowledgeRepository


class InMemoryKnowledgeRepository(KnowledgeRepository):
    """Deterministic, process-local repository. No hidden global state."""

    def __init__(self) -> None:
        self._records: dict[str, KnowledgeRecord] = {}

    def save(self, record: KnowledgeRecord) -> None:
        self._records[record.knowledge_id] = record

    def get(self, knowledge_id: str) -> KnowledgeRecord | None:
        return self._records.get(knowledge_id)

    def all_records(self) -> tuple[KnowledgeRecord, ...]:
        return tuple(self._records[k] for k in sorted(self._records))

    def find(
        self,
        *,
        subject: str | None = None,
        layer: KnowledgeLayer | None = None,
    ) -> tuple[KnowledgeRecord, ...]:
        def matches(r: KnowledgeRecord) -> bool:
            if subject is not None and r.subject != subject:
                return False
            return not (layer is not None and r.layer is not layer)

        return tuple(r for r in self.all_records() if matches(r))

"""JSON-file-backed knowledge repository.

Each record is stored as ``<knowledge_id>.json`` in a directory, written
atomically (temp file + rename) so a crash never leaves a half-written record.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..domain.knowledge import KnowledgeLayer, KnowledgeRecord
from ..interfaces.repository import KnowledgeRepository


class JsonKnowledgeRepository(KnowledgeRepository):
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    def _path(self, knowledge_id: str) -> Path:
        return self.directory / f"{knowledge_id}.json"

    def save(self, record: KnowledgeRecord) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self._path(record.knowledge_id)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(record.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, target)

    def get(self, knowledge_id: str) -> KnowledgeRecord | None:
        path = self._path(knowledge_id)
        if not path.exists():
            return None
        return KnowledgeRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def all_records(self) -> tuple[KnowledgeRecord, ...]:
        self.directory.mkdir(parents=True, exist_ok=True)
        records = []
        for path in sorted(self.directory.glob("*.json")):
            records.append(
                KnowledgeRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
            )
        return tuple(records)

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

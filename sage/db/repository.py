"""Base repository helpers."""

from __future__ import annotations

import json
from typing import Any

from sage.db.connection import Database


class BaseRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def dumps(data: Any) -> str:
        return json.dumps(data, ensure_ascii=False, default=str)

    @staticmethod
    def loads(raw: str | None, default: Any = None) -> Any:
        if raw is None or raw == "":
            return default if default is not None else {}
        return json.loads(raw)

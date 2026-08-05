"""File manager protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso


class FileRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("file"))
    path: str
    mime_type: str | None = None
    checksum: str | None = None
    size_bytes: int | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    indexed_at: str = Field(default_factory=utcnow_iso)


@runtime_checkable
class FileManager(Protocol):
    async def index(self, path: Path | str) -> FileRecord: ...

    async def search(self, query: str) -> list[FileRecord]: ...

    async def watch(self, directory: Path | str) -> None: ...

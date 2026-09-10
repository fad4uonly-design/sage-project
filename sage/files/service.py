"""File manager implementation."""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.db.connection import Database
from sage.db.repository import BaseRepository
from sage.events.bus import EventBus
from sage.events.events import Event
from sage.files.interfaces import FileManager, FileRecord
from sage.logging import get_logger

log = get_logger(__name__)


class DefaultFileManager(BaseRepository):
    def __init__(self, db: Database, events: EventBus | None = None) -> None:
        super().__init__(db)
        self._events = events
        self._watched: list[str] = []

    async def index(self, path: Path | str) -> FileRecord:
        p = Path(path).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(str(p))
        raw = p.read_bytes()
        checksum = hashlib.sha256(raw).hexdigest()
        mime = mimetypes.guess_type(str(p))[0]
        record = FileRecord(
            path=str(p),
            mime_type=mime,
            checksum=checksum,
            size_bytes=len(raw),
            tags=[p.suffix.lstrip(".").lower()] if p.suffix else [],
            metadata={"name": p.name},
        )
        await self.db.execute(
            """
            INSERT INTO files (id, path, mime_type, checksum, size_bytes, tags, metadata, indexed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                mime_type = excluded.mime_type,
                checksum = excluded.checksum,
                size_bytes = excluded.size_bytes,
                tags = excluded.tags,
                metadata = excluded.metadata,
                indexed_at = excluded.indexed_at
            """,
            (
                record.id,
                record.path,
                record.mime_type,
                record.checksum,
                record.size_bytes,
                self.dumps(record.tags),
                self.dumps(record.metadata),
                record.indexed_at,
            ),
        )
        # Re-read id if conflict updated existing
        row = await self.db.fetchone("SELECT id FROM files WHERE path = ?", (record.path,))
        if row:
            record.id = row["id"]

        if self._events:
            await self._events.publish(
                Event(
                    type="files.indexed",
                    payload={"id": record.id, "path": record.path},
                    source="files",
                )
            )
        log.debug("files.indexed", path=record.path)
        return record

    async def search(self, query: str) -> list[FileRecord]:
        q = f"%{query}%"
        rows = await self.db.fetchall(
            """
            SELECT * FROM files
            WHERE path LIKE ? OR tags LIKE ? OR metadata LIKE ?
            ORDER BY indexed_at DESC
            LIMIT 50
            """,
            (q, q, q),
        )
        return [
            FileRecord(
                id=r["id"],
                path=r["path"],
                mime_type=r["mime_type"],
                checksum=r["checksum"],
                size_bytes=r["size_bytes"],
                tags=self.loads(r["tags"], []),
                metadata=self.loads(r["metadata"], {}),
                indexed_at=r["indexed_at"],
            )
            for r in rows
        ]

    async def watch(self, directory: Path | str) -> None:
        # Full watchdog integration in later milestone — record intent for now
        path = str(Path(directory).expanduser().resolve())
        self._watched.append(path)
        log.info("files.watch_registered", path=path)

    async def count(self) -> int:
        val = await self.db.scalar("SELECT COUNT(*) FROM files")
        return int(val or 0)


class FileModule(BaseModule):
    name = "files"
    version = "0.1.0"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._mgr: DefaultFileManager | None = None

    async def _on_initialize(self) -> None:
        db = self.container.resolve(Database)
        events = self.container.try_resolve(EventBus)
        self._mgr = DefaultFileManager(db, events)
        self.container.register_instance(FileManager, self._mgr)
        self.container.register_instance(DefaultFileManager, self._mgr)

    async def _on_health(self) -> HealthStatus | None:
        if self._mgr is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        return HealthStatus.healthy(self.name, "ok", files=await self._mgr.count())

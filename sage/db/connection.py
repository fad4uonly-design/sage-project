"""SQLite database connection manager (async via aiosqlite)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import aiosqlite

from sage.logging import get_logger

log = get_logger(__name__)


class Database:
    """Thin async wrapper around a single SQLite database file."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._conn: aiosqlite.Connection | None = None

    @property
    def is_open(self) -> bool:
        return self._conn is not None

    async def open(self) -> None:
        if self._conn is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.execute("PRAGMA journal_mode = WAL")
        log.info("db.opened", path=str(self.path))

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            log.info("db.closed", path=str(self.path))

    def _require(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not open")
        return self._conn

    async def execute(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> aiosqlite.Cursor:
        conn = self._require()
        cur = await conn.execute(sql, params)
        await conn.commit()
        return cur

    async def executemany(self, sql: str, seq: list[tuple[Any, ...]]) -> None:
        conn = self._require()
        await conn.executemany(sql, seq)
        await conn.commit()

    async def executescript(self, script: str) -> None:
        conn = self._require()
        await conn.executescript(script)
        await conn.commit()

    async def fetchone(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> aiosqlite.Row | None:
        conn = self._require()
        async with conn.execute(sql, params) as cur:
            return await cur.fetchone()

    async def fetchall(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> list[aiosqlite.Row]:
        conn = self._require()
        async with conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
            return list(rows)

    async def scalar(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> Any:
        row = await self.fetchone(sql, params)
        if row is None:
            return None
        return row[0]

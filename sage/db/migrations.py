"""Simple numbered SQL migration runner."""

from __future__ import annotations

from pathlib import Path

from sage.db.connection import Database
from sage.logging import get_logger
from sage.utils.time import utcnow_iso

log = get_logger(__name__)

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

# Future migrations append here: (version, name, sql_or_callable)
MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "initial_schema", _SCHEMA_PATH.read_text(encoding="utf-8")),
]


async def current_version(db: Database) -> int:
    row = await db.fetchone(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    )
    if row is None:
        return 0
    ver = await db.scalar("SELECT COALESCE(MAX(version), 0) FROM schema_migrations")
    return int(ver or 0)


async def apply_migrations(db: Database) -> int:
    """Apply all pending migrations. Returns resulting schema version."""
    version = await current_version(db)
    applied = 0

    for mig_version, name, sql in MIGRATIONS:
        if mig_version <= version:
            continue
        log.info("db.migrate", version=mig_version, name=name)
        await db.executescript(sql)
        # Ensure migrations table exists even if script created it
        await db.execute(
            "INSERT OR REPLACE INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
            (mig_version, name, utcnow_iso()),
        )
        applied += 1
        version = mig_version

    if applied:
        log.info("db.migrations_applied", count=applied, version=version)
    else:
        log.debug("db.migrations_up_to_date", version=version)
    return version

"""Simple numbered SQL migration runner."""

from __future__ import annotations

from pathlib import Path

from sage.db.connection import Database
from sage.logging import get_logger
from sage.utils.time import utcnow_iso

log = get_logger(__name__)

_DIR = Path(__file__).resolve().parent

MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "initial_schema", (_DIR / "schema.sql").read_text(encoding="utf-8")),
    (2, "foundation_v011", (_DIR / "migrations_v2.sql").read_text(encoding="utf-8")),
    (3, "intelligence_v020", (_DIR / "migrations_v3.sql").read_text(encoding="utf-8")),
    (4, "automation_v040", (_DIR / "migrations_v4.sql").read_text(encoding="utf-8")),
    (5, "context_v050", (_DIR / "migrations_v5.sql").read_text(encoding="utf-8")),
    (6, "discovery_ux_v060", (_DIR / "migrations_v6.sql").read_text(encoding="utf-8")),
    (7, "self_improvement_v070", (_DIR / "migrations_v7.sql").read_text(encoding="utf-8")),
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

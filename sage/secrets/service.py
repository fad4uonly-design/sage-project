"""Secrets manager implementation and module."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sage.config.settings import Settings
from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.db.connection import Database
from sage.db.repository import BaseRepository
from sage.logging import get_logger
from sage.secrets.crypto import SecretBox, SealedSecret, generate_master_key
from sage.secrets.interfaces import SecretsManager
from sage.utils.time import utcnow_iso

log = get_logger(__name__)

_MASTER_ENV = "SAGE_MASTER_KEY"
_MASTER_FILE = "master.key"


class LocalSecretsManager(BaseRepository):
    """
    Encrypted secret store in SQLite.

    Master key resolution order:
      1. SAGE_MASTER_KEY env
      2. $SAGE_DATA_DIR/config/master.key (created on first run if missing)
    """

    def __init__(self, db: Database, box: SecretBox, master_key_path: Path | None = None) -> None:
        super().__init__(db)
        self._box = box
        self._master_key_path = master_key_path

    async def set_secret(
        self, key: str, value: str, *, metadata: dict[str, Any] | None = None
    ) -> None:
        sealed = self._box.seal(value)
        now = utcnow_iso()
        await self.db.execute(
            """
            INSERT INTO secrets (key, ciphertext, salt, nonce, metadata, created_at, updated_at, rotated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(key) DO UPDATE SET
                ciphertext = excluded.ciphertext,
                salt = excluded.salt,
                nonce = excluded.nonce,
                metadata = excluded.metadata,
                updated_at = excluded.updated_at
            """,
            (
                key,
                sealed.ciphertext_b64,
                sealed.salt_b64,
                sealed.nonce_b64,
                self.dumps(metadata or {}),
                now,
                now,
            ),
        )
        log.info("secrets.set", key=key)

    async def get_secret(self, key: str) -> str | None:
        row = await self.db.fetchone("SELECT * FROM secrets WHERE key = ?", (key,))
        if row is None:
            return None
        sealed = SealedSecret(
            salt_b64=row["salt"],
            nonce_b64=row["nonce"],
            ciphertext_b64=row["ciphertext"],
        )
        return self._box.open(sealed)

    async def delete_secret(self, key: str) -> bool:
        cur = await self.db.execute("DELETE FROM secrets WHERE key = ?", (key,))
        deleted = (cur.rowcount or 0) > 0
        if deleted:
            log.info("secrets.deleted", key=key)
        return deleted

    async def list_keys(self) -> list[str]:
        rows = await self.db.fetchall("SELECT key FROM secrets ORDER BY key")
        return [r["key"] for r in rows]

    async def rotate(self, key: str, new_value: str) -> None:
        existing = await self.db.fetchone("SELECT metadata FROM secrets WHERE key = ?", (key,))
        meta = self.loads(existing["metadata"], {}) if existing else {}
        sealed = self._box.seal(new_value)
        now = utcnow_iso()
        await self.db.execute(
            """
            INSERT INTO secrets (key, ciphertext, salt, nonce, metadata, created_at, updated_at, rotated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                ciphertext = excluded.ciphertext,
                salt = excluded.salt,
                nonce = excluded.nonce,
                updated_at = excluded.updated_at,
                rotated_at = excluded.rotated_at
            """,
            (
                key,
                sealed.ciphertext_b64,
                sealed.salt_b64,
                sealed.nonce_b64,
                self.dumps(meta),
                now,
                now,
                now,
            ),
        )
        log.info("secrets.rotated", key=key)

    async def has(self, key: str) -> bool:
        val = await self.db.scalar("SELECT 1 FROM secrets WHERE key = ?", (key,))
        return val is not None

    async def count(self) -> int:
        return int(await self.db.scalar("SELECT COUNT(*) FROM secrets") or 0)


def resolve_master_key(data_dir: Path) -> tuple[str, Path]:
    """Load or create the master key. Returns (key, path_written_or_used)."""
    env = os.environ.get(_MASTER_ENV)
    path = data_dir / "config" / _MASTER_FILE
    if env:
        return env, path
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        return path.read_text(encoding="utf-8").strip(), path
    key = generate_master_key()
    path.write_text(key + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    log.warning(
        "secrets.master_key_created",
        path=str(path),
        msg="Back up this file. Prefer SAGE_MASTER_KEY env in production.",
    )
    return key, path


class SecretsModule(BaseModule):
    name = "secrets"
    version = "0.1.1"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._mgr: LocalSecretsManager | None = None

    async def _on_initialize(self) -> None:
        settings = self.container.resolve(Settings)
        db = self.container.resolve(Database)
        master, path = resolve_master_key(settings.data_dir)
        box = SecretBox(master)
        self._mgr = LocalSecretsManager(db, box, master_key_path=path)
        self.container.register_instance(SecretsManager, self._mgr)
        self.container.register_instance(LocalSecretsManager, self._mgr)

        # Seed known API keys from settings/env into secret store if present and not already stored
        await self._seed_from_settings(settings)

    async def _seed_from_settings(self, settings: Settings) -> None:
        assert self._mgr is not None
        mapping = {
            "openai_api_key": settings.models.openai_api_key,
            "anthropic_api_key": settings.models.anthropic_api_key,
        }
        for key, value in mapping.items():
            if value and not await self._mgr.has(key):
                await self._mgr.set_secret(key, value, metadata={"source": "settings_seed"})

    async def _on_health(self) -> HealthStatus | None:
        if self._mgr is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        n = await self._mgr.count()
        return HealthStatus.healthy(self.name, "ok", secrets=n)

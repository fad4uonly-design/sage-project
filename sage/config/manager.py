"""
Runtime Configuration Manager.

Layers:
  defaults.yaml → user YAML/JSON → env → DB profile store → runtime overrides
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from sage.config.loader import load_settings
from sage.config.settings import Settings
from sage.db.connection import Database
from sage.db.repository import BaseRepository
from sage.logging import get_logger
from sage.utils.time import utcnow_iso

log = get_logger(__name__)


class ConfigurationManager:
    """
    Unified config façade.

    - `settings` is the typed boot-time Settings object
    - DB `config_store` holds runtime/user-profile key-values
    - YAML/JSON user files can be reloaded
    """

    def __init__(
        self,
        settings: Settings,
        db: Database | None = None,
        *,
        profile: str = "default",
    ) -> None:
        self.db = db
        self._repo = BaseRepository(db) if db is not None else None
        self._settings = settings
        self._profile = profile
        self._runtime: dict[str, Any] = {}

    def _dumps(self, data: Any) -> str:
        if self._repo:
            return self._repo.dumps(data)
        import json

        return json.dumps(data, ensure_ascii=False, default=str)

    def _loads(self, raw: str | None, default: Any = None) -> Any:
        if self._repo:
            return self._repo.loads(raw, default)
        import json

        if raw is None or raw == "":
            return default if default is not None else {}
        return json.loads(raw)

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def profile(self) -> str:
        return self._profile

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._runtime:
            return self._runtime[key]
        # dotted access into settings
        cur: Any = self._settings
        for part in key.split("."):
            if hasattr(cur, part):
                cur = getattr(cur, part)
            elif isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return default
        return cur

    def set_runtime(self, key: str, value: Any) -> None:
        self._runtime[key] = value
        log.info("config.runtime_set", key=key)

    async def set_profile_value(self, key: str, value: Any) -> None:
        if self.db is None:
            self.set_runtime(key, value)
            return
        await self.db.execute(
            """
            INSERT INTO config_store (key, value, profile, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                profile = excluded.profile,
                updated_at = excluded.updated_at
            """,
            (key, self._dumps(value), self._profile, utcnow_iso()),
        )
        self._runtime[key] = value
        log.info("config.profile_set", key=key, profile=self._profile)

    async def get_profile_value(self, key: str, default: Any = None) -> Any:
        if key in self._runtime:
            return self._runtime[key]
        if self.db is None:
            return default
        row = await self.db.fetchone(
            "SELECT value FROM config_store WHERE key = ? AND profile = ?",
            (key, self._profile),
        )
        if row is None:
            return default
        return self._loads(row["value"], default)

    async def load_profile(self, profile: str | None = None) -> dict[str, Any]:
        profile = profile or self._profile
        if self.db is None:
            return dict(self._runtime)
        rows = await self.db.fetchall(
            "SELECT key, value FROM config_store WHERE profile = ?",
            (profile,),
        )
        data = {r["key"]: self._loads(r["value"]) for r in rows}
        self._runtime.update(data)
        self._profile = profile
        return data

    def reload_files(self, *, config_file: str | Path | None = None) -> Settings:
        """Reload settings from disk/env (does not drop runtime overrides)."""
        self._settings = load_settings(config_file=config_file)
        log.info("config.reloaded")
        return self._settings

    def export_user_yaml(self, path: Path | str) -> None:
        path = Path(path)
        data = self._settings.model_dump(mode="json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    def export_user_json(self, path: Path | str) -> None:
        path = Path(path)
        data = self._settings.model_dump(mode="json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def bind_db(self, db: Database) -> None:
        self.db = db
        self._repo = BaseRepository(db)

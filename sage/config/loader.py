"""Load and merge SAGE configuration from multiple sources."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from sage.config.settings import Settings

_PACKAGE_DIR = Path(__file__).resolve().parent
_DEFAULTS_PATH = _PACKAGE_DIR / "defaults.yaml"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file must be a mapping: {path}")
    return data


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override into base (override wins)."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_settings(
    *,
    config_file: Path | str | None = None,
    env_file: Path | str | None = ".env",
    overrides: dict[str, Any] | None = None,
    load_env: bool = True,
) -> Settings:
    """
    Build a validated Settings instance.

    Merge order (later wins):
      1. Package defaults.yaml
      2. User config file (explicit path, or $SAGE_DATA_DIR/config/sage.yaml)
      3. Environment variables (SAGE_*)
      4. Explicit overrides dict (CLI)
    """
    if load_env and env_file is not None:
        env_path = Path(env_file)
        if env_path.is_file():
            load_dotenv(env_path, override=False)

    merged: dict[str, Any] = _read_yaml(_DEFAULTS_PATH)

    # Early peek at data_dir from env for locating user config
    data_dir = Path(os.environ.get("SAGE_DATA_DIR", merged.get("data_dir", "./data"))).expanduser()

    user_config_candidates: list[Path] = []
    if config_file is not None:
        user_config_candidates.append(Path(config_file))
    else:
        user_config_candidates.append(data_dir / "config" / "sage.yaml")
        user_config_candidates.append(Path("sage.yaml"))

    for candidate in user_config_candidates:
        if candidate.is_file():
            merged = _deep_merge(merged, _read_yaml(candidate))
            break

    # Env overrides YAML. Explicit CLI `overrides` win last.
    # (pydantic-settings prefers init kwargs over env, so we fold env into the dict.)
    merged = _deep_merge(merged, _read_env_overrides())

    if overrides:
        merged = _deep_merge(merged, overrides)

    settings = Settings(**merged)
    return settings


def _read_env_overrides() -> dict[str, Any]:
    """Translate SAGE_* / SAGE__NESTED__KEY env vars into a nested dict."""
    prefix = "SAGE_"
    result: dict[str, Any] = {}

    for raw_key, raw_val in os.environ.items():
        if not raw_key.startswith(prefix):
            continue
        key = raw_key[len(prefix) :]
        if not key:
            continue
        # Support both SAGE_LOGGING__LEVEL and SAGE_LOGGING_LEVEL for nested
        parts = [p.lower() for p in key.split("__") if p]
        if len(parts) == 1 and "_" in parts[0]:
            # Map well-known top-level flat keys only; nested handled via __
            pass

        cursor: dict[str, Any] = result
        for part in parts[:-1]:
            nxt = cursor.setdefault(part.lower(), {})
            if not isinstance(nxt, dict):
                nxt = {}
                cursor[part.lower()] = nxt
            cursor = nxt
        leaf = parts[-1].lower()
        cursor[leaf] = _coerce_env_value(raw_val)

    return result


def _coerce_env_value(value: str) -> Any:
    lowered = value.strip().lower()
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value

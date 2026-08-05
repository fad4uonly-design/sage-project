"""Configuration loader tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sage.config.loader import load_settings


def test_load_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAGE_ENV", raising=False)
    monkeypatch.chdir(tmp_path)
    settings = load_settings(env_file=None, load_env=False)
    assert settings.models.default_provider == "stub"
    assert settings.memory.default_recall_limit == 10


def test_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAGE_ENV", "production")
    monkeypatch.setenv("SAGE_DATA_DIR", str(tmp_path / "d"))
    settings = load_settings(env_file=None, load_env=False)
    assert settings.env == "production"

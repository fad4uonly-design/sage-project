"""Configuration loader tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from sage.config.loader import load_settings

REPO_ROOT = Path(__file__).resolve().parents[2]

# SAGE_MODELS__* keys that a local .env can use to override model slots.
_MODEL_ENV_KEYS = (
    "SAGE_MODELS__DEFAULT_PROVIDER",
    "SAGE_MODELS__DEFAULT_MODEL_NAME",
    "SAGE_MODELS__LOCAL_MODEL_NAME",
    "SAGE_MODELS__LOCAL_BASE_URL",
)


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


def test_repo_sage_yaml_declares_local_gemma3_brain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin the SAGE brain via the real loader path when sage.yaml exists.

    NOTE: sage.yaml is a *local, gitignored* config file (not tracked), so
    this test skips on machines/CI checkouts where it is absent. Where it
    exists it must load through load_settings() as: provider=local,
    model=gemma3:4b, Ollama base URL — isolated from any local .env / shell
    env so it tests exactly this file's declared configuration.
    """
    repo_yaml = REPO_ROOT / "sage.yaml"
    if not repo_yaml.is_file():
        pytest.skip("sage.yaml is a local (gitignored) config; not present here")
    for key in _MODEL_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    settings = load_settings(
        config_file=REPO_ROOT / "sage.yaml",
        env_file=None,
        load_env=False,
    )
    assert settings.models.default_provider == "local"
    assert settings.models.default_model_name == "gemma3:4b"
    assert settings.models.local_model_name == "gemma3:4b"
    assert settings.models.local_base_url == "http://127.0.0.1:11434/v1"


def test_local_env_model_overrides_beat_user_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: SAGE_MODELS__* env (e.g. from a local .env) must win over
    the user sage.yaml model slots.

    This precedence is what let a stale qwen2.5:1.5b local .env silently
    override the repository's sage.yaml brain. Uses sentinel values only —
    the tracked suite must never depend on this machine's .env contents.
    """
    monkeypatch.chdir(tmp_path)
    for key in _MODEL_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    (tmp_path / "sage.yaml").write_text(
        "models:\n"
        "  default_provider: local\n"
        "  default_model_name: yaml-model:1b\n"
        "  local_model_name: yaml-model:1b\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SAGE_MODELS__DEFAULT_PROVIDER", "local")
    monkeypatch.setenv("SAGE_MODELS__DEFAULT_MODEL_NAME", "env-model:2b")
    monkeypatch.setenv("SAGE_MODELS__LOCAL_MODEL_NAME", "env-model:2b")
    monkeypatch.setenv("SAGE_MODELS__LOCAL_BASE_URL", "http://127.0.0.1:11434/v1")

    settings = load_settings(env_file=None, load_env=False)

    assert settings.models.default_model_name == "env-model:2b"
    assert settings.models.local_model_name == "env-model:2b"
    assert settings.models.default_provider == "local"
    assert settings.models.local_base_url == "http://127.0.0.1:11434/v1"

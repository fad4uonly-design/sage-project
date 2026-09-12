"""Tests for ModelsSettings extensions and PerceptionSettings (Phase 4 slots)."""

from __future__ import annotations

import pytest
from sage.config.settings import ModelsSettings, PerceptionSettings, Settings


def test_models_settings_embedding_defaults() -> None:
    settings = ModelsSettings()
    assert settings.embedding_provider == "stub"
    assert settings.embedding_model_name == "nomic-embed-text"
    assert settings.embedding_dim == 256


def test_models_settings_serving_runtime_default() -> None:
    assert ModelsSettings().serving_runtime == "auto"


def test_models_settings_local_defaults() -> None:
    settings = ModelsSettings()
    assert settings.local_base_url == "http://127.0.0.1:11434/v1"
    assert settings.local_model_name == "local-model"
    assert settings.local_timeout == 120.0


def test_perception_settings_off_by_default() -> None:
    settings = PerceptionSettings()
    assert settings.vision_provider == "none"
    assert settings.speech_provider == "none"
    assert settings.vision_base_url == "http://127.0.0.1:11434/v1"
    assert settings.speech_base_url == "http://127.0.0.1:8080"
    assert settings.vision_model_name == "smolvlm"
    assert settings.speech_model_name == "whisper"
    assert settings.vision_timeout == 120.0
    assert settings.speech_timeout == 120.0


def test_settings_wires_perception_by_default() -> None:
    settings = Settings()
    assert isinstance(settings.perception, PerceptionSettings)
    assert settings.perception.vision_provider == "none"
    assert settings.perception.speech_provider == "none"


def test_models_embedding_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAGE_MODELS__EMBEDDING_PROVIDER", "hashing")
    settings = Settings()
    assert settings.models.embedding_provider == "hashing"

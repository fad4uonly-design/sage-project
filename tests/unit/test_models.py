"""Model provider routing tests."""

from __future__ import annotations

from pathlib import Path

from sage.config.settings import (
    LoggingSettings,
    ModelsSettings,
    PluginsSettings,
    SchedulerSettings,
    Settings,
)
from sage.models.interfaces import LanguageModel
from sage.models.local._adapter import LocalLanguageModel
from sage.models.router import DefaultModelRouter
from sage.models.stub import StubLanguageModel


def make_settings(
    tmp_path: Path,
    provider: str = "stub",
    model_name: str = "test-model",
) -> Settings:
    data = tmp_path / "data"

    return Settings(
        env="test",
        data_dir=data,
        db_path=data / "test_sage.db",
        models=ModelsSettings(
            default_provider=provider,
            default_model_name=model_name,
        ),
        logging=LoggingSettings(level="WARNING", format="console"),
        scheduler=SchedulerSettings(enabled=False),
        plugins=PluginsSettings(enabled=False, auto_load=False),
    )


def test_stub_provider(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path,
        provider="stub",
        model_name="test-stub",
    )

    router = DefaultModelRouter(settings)
    model = router.get_language_model()

    assert isinstance(model, StubLanguageModel)
    assert isinstance(model, LanguageModel)
    assert model.provider == "stub"
    assert model.model_name == "test-stub"


def test_unknown_provider_falls_back_to_stub(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path,
        provider="unknown-provider",
        model_name="fallback-test",
    )

    router = DefaultModelRouter(settings)
    model = router.get_language_model()

    assert isinstance(model, StubLanguageModel)
    assert model.provider == "stub"
    assert model.model_name == "fallback-test"


def test_local_provider(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path,
        provider="local",
        model_name="test-local-model",
    )

    router = DefaultModelRouter(settings)
    model = router.get_language_model()

    assert isinstance(model, LocalLanguageModel)
    assert isinstance(model, LanguageModel)
    assert model.provider == "local"
    assert model.model_name == settings.models.local_model_name
    assert settings.models.local_base_url == "http://127.0.0.1:11434/v1"
    assert settings.models.local_timeout == 120.0

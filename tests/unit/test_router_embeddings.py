"""Router embedding selection tests (TurboVec slot behind config)."""

from __future__ import annotations

from pathlib import Path

from sage.config.settings import Settings
from sage.models.local_embedding import HashingEmbeddingModel, LocalEmbeddingModel
from sage.models.router import DefaultModelRouter
from sage.models.stub import StubEmbeddingModel, StubLanguageModel


def make_settings(
    tmp_path: Path,
    *,
    provider: str = "stub",
    embedding_provider: str = "stub",
) -> Settings:
    data = tmp_path / "data"

    return Settings(
        env="test",
        data_dir=data,
        db_path=data / "test_sage.db",
        models={
            "default_provider": provider,
            "default_model_name": "test-model",
            "embedding_provider": embedding_provider,
        },
        logging={"level": "WARNING", "format": "console"},
        scheduler={"enabled": False},
        plugins={"enabled": False, "auto_load": False},
    )


def test_default_embedding_is_stub(tmp_path: Path) -> None:
    router = DefaultModelRouter(make_settings(tmp_path))

    assert isinstance(router.get_embedding_model(), StubEmbeddingModel)


def test_hashing_embedding_selected(tmp_path: Path) -> None:
    router = DefaultModelRouter(
        make_settings(tmp_path, embedding_provider="hashing")
    )

    embedding = router.get_embedding_model()

    assert isinstance(embedding, HashingEmbeddingModel)
    assert embedding.provider == "hashing"


def test_local_embedding_selected(tmp_path: Path) -> None:
    router = DefaultModelRouter(
        make_settings(tmp_path, provider="local", embedding_provider="local")
    )

    embedding = router.get_embedding_model()

    assert isinstance(embedding, LocalEmbeddingModel)
    assert embedding.model_name == "nomic-embed-text"


def test_embedding_choice_is_independent_of_language_provider(tmp_path: Path) -> None:
    router = DefaultModelRouter(
        make_settings(tmp_path, provider="stub", embedding_provider="hashing")
    )

    assert isinstance(router.get_language_model(), StubLanguageModel)
    assert isinstance(router.get_embedding_model(), HashingEmbeddingModel)

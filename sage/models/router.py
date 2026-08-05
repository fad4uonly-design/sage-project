"""Model router — selects providers by config."""

from __future__ import annotations

from sage.config.settings import Settings
from sage.logging import get_logger
from sage.models.interfaces import EmbeddingModel, LanguageModel
from sage.models.stub import StubEmbeddingModel, StubLanguageModel

log = get_logger(__name__)


class DefaultModelRouter:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lm: LanguageModel | None = None
        self._emb: EmbeddingModel | None = None
        self._init_providers()

    def _init_providers(self) -> None:
        provider = self._settings.models.default_provider.lower()
        name = self._settings.models.default_model_name

        if provider == "stub":
            self._lm = StubLanguageModel(name)
            self._emb = StubEmbeddingModel()
        elif provider == "openai":
            # Lazy optional import path — fall back to stub if unavailable/unconfigured
            self._lm = self._try_openai(name) or StubLanguageModel(name)
            self._emb = StubEmbeddingModel()
        elif provider == "anthropic":
            self._lm = self._try_anthropic(name) or StubLanguageModel(name)
            self._emb = StubEmbeddingModel()
        else:
            log.warning("models.unknown_provider", provider=provider, falling_back="stub")
            self._lm = StubLanguageModel(name)
            self._emb = StubEmbeddingModel()

        log.info(
            "models.router_ready",
            provider=self._lm.provider,
            model=self._lm.model_name,
        )

    def _try_openai(self, name: str) -> LanguageModel | None:
        key = self._settings.models.openai_api_key
        if not key:
            log.info("models.openai_no_key", msg="Using stub")
            return None
        try:
            from sage.models.openai_adapter import OpenAILanguageModel

            return OpenAILanguageModel(api_key=key, model_name=name)
        except Exception as exc:
            log.warning("models.openai_unavailable", error=str(exc))
            return None

    def _try_anthropic(self, name: str) -> LanguageModel | None:
        key = self._settings.models.anthropic_api_key
        if not key:
            log.info("models.anthropic_no_key", msg="Using stub")
            return None
        try:
            from sage.models.anthropic_adapter import AnthropicLanguageModel

            return AnthropicLanguageModel(api_key=key, model_name=name)
        except Exception as exc:
            log.warning("models.anthropic_unavailable", error=str(exc))
            return None

    def get_language_model(self, *, capability: str | None = None) -> LanguageModel:
        assert self._lm is not None
        return self._lm

    def get_embedding_model(self) -> EmbeddingModel:
        assert self._emb is not None
        return self._emb

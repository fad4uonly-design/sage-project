"""Model adapter protocols."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: str  # system | user | assistant | tool
    content: str


class CompletionRequest(BaseModel):
    messages: list[Message]
    temperature: float | None = None
    max_tokens: int | None = None
    stop: list[str] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    response_schema: dict[str, Any] | None = None
    """Optional JSON Schema the reply must satisfy.

    ``None`` means ordinary free-form generation. When set, an adapter that
    supports constrained decoding translates it into the provider's native
    mechanism (Ollama/OpenAI ``response_format``); callers then parse a reply
    that is already constrained to their contract instead of scraping text.
    """


class CompletionResponse(BaseModel):
    content: str
    model: str
    provider: str
    usage: dict[str, int] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)
    finish_reason: str = "stop"


@runtime_checkable
class LanguageModel(Protocol):
    @property
    def provider(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    async def complete(self, request: CompletionRequest) -> CompletionResponse: ...


@runtime_checkable
class EmbeddingModel(Protocol):
    @property
    def provider(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


@runtime_checkable
class ModelRouter(Protocol):
    def get_language_model(self, *, capability: str | None = None) -> LanguageModel: ...

    def get_embedding_model(self) -> EmbeddingModel: ...


# -- Perception roles (Phase 4) ---------------------------------------------
#
# Vision and speech are new I/O surfaces, deliberately NOT forced through the
# chat-completion API. Each gets its own typed interface so a perception model
# can be evaluated and replaced independently of the language layer.


class ImageInput(BaseModel):
    """An image to describe: either base64 data or a URL reference."""

    data: str
    """Base64-encoded bytes, or a URL when ``is_url`` is True."""
    is_url: bool = False
    mime_type: str = "image/jpeg"

    def as_data_url(self) -> str:
        if self.is_url:
            return self.data
        return f"data:{self.mime_type};base64,{self.data}"


@runtime_checkable
class VisionModel(Protocol):
    """Image understanding (e.g. SmolVLM behind a local endpoint)."""

    @property
    def provider(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    async def describe(
        self,
        image: ImageInput,
        *,
        question: str | None = None,
    ) -> str:
        """Describe ``image``, or answer ``question`` about it."""
        ...


@runtime_checkable
class AudioTranscriber(Protocol):
    """Speech-to-text (e.g. Whisper Tiny behind a local endpoint)."""

    @property
    def provider(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    async def transcribe(
        self,
        audio: bytes,
        *,
        filename: str = "audio.wav",
        language: str | None = None,
    ) -> str:
        """Transcribe ``audio`` bytes to text."""
        ...

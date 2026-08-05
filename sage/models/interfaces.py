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

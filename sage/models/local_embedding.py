"""Embedding model adapters: local endpoint + offline hashing fallback.

TurboVec concept: a replaceable embedding source behind the EmbeddingModel
protocol. `LocalEmbeddingModel` talks to any OpenAI-compatible `/embeddings`
endpoint (Ollama `/v1`, llama.cpp server, vLLM); `HashingEmbeddingModel` is a
deterministic offline fallback so similarity plumbing works with no server.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from typing import Any

import httpx

from sage.logging import get_logger
from sage.models.interfaces import EmbeddingModel

log = get_logger(__name__)


class HashingEmbeddingModel:
    """Deterministic feature-hashing embeddings (offline, no server needed).

    Unigrams and bigrams are hashed into a fixed-size, L2-normalized vector.
    Not truly semantic, but stable and dependency-free — good enough to keep
    similarity ranking meaningful in tests and offline development.
    """

    def __init__(self, dim: int = 256) -> None:
        if dim < 16:
            raise ValueError("HashingEmbeddingModel dim must be >= 16")
        self._dim = dim

    @property
    def provider(self) -> str:
        return "hashing"

    @property
    def model_name(self) -> str:
        return f"feature-hash-{self._dim}d"

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        tokens = [t for t in text.lower().split() if t]
        grams = tokens + [f"{a}·{b}" for a, b in zip(tokens, tokens[1:], strict=False)]
        for gram in grams:
            digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "little")
            index = value % self._dim
            sign = 1.0 if value & (1 << 63) else -1.0
            vec[index] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text or "") for text in texts]


class LocalEmbeddingModel:
    """Embeddings from an OpenAI-compatible local endpoint.

    Works with Ollama (`http://127.0.0.1:11434/v1`), llama.cpp server, and
    vLLM — anything exposing `POST {base_url}/embeddings`. Both the OpenAI
    response format (`data[].embedding`) and the Ollama native format
    (`embeddings`) are accepted.
    """

    def __init__(
        self,
        base_url: str,
        model_name: str = "nomic-embed-text",
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model_name = model_name
        self._timeout = timeout
        self._transport = transport

    @property
    def provider(self) -> str:
        return "local"

    @property
    def model_name(self) -> str:
        return self._model_name

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []

        payload = {"model": self._model_name, "input": list(texts)}
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport
        ) as client:
            response = await client.post(
                f"{self._base_url}/embeddings",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        return self._parse_response(data, expected=len(texts))

    def _parse_response(self, data: Any, *, expected: int) -> list[list[float]]:
        vectors: list[list[float]] | None = None

        if isinstance(data, dict) and isinstance(data.get("data"), list):
            rows = sorted(data["data"], key=lambda row: row.get("index", 0))
            vectors = [[float(x) for x in row["embedding"]] for row in rows]
        elif isinstance(data, dict) and isinstance(data.get("embeddings"), list):
            vectors = [[float(x) for x in vec] for vec in data["embeddings"]]

        if vectors is None:
            raise RuntimeError("Unrecognized embedding response format.")
        if len(vectors) != expected:
            raise RuntimeError(
                f"Embedding count mismatch: got {len(vectors)}, expected {expected}"
            )
        return vectors


def _assert_protocols() -> None:
    _: EmbeddingModel = HashingEmbeddingModel()
    __: EmbeddingModel = LocalEmbeddingModel(base_url="http://127.0.0.1:11434/v1")

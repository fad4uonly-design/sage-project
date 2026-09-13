"""Embedding adapter tests (TurboVec concept: replaceable embedding source)."""

from __future__ import annotations

import json

import httpx
import pytest
from sage.models.interfaces import EmbeddingModel
from sage.models.local_embedding import HashingEmbeddingModel, LocalEmbeddingModel


async def test_hashing_deterministic_and_normalized() -> None:
    model = HashingEmbeddingModel(dim=128)

    [first] = await model.embed(["greenhouse tomato sales"])
    [again] = await model.embed(["greenhouse tomato sales"])
    [other] = await model.embed(["flight booking to tokyo"])

    assert first == again
    assert first != other
    assert len(first) == 128
    assert abs(sum(x * x for x in first) - 1.0) < 1e-6
    assert model.provider == "hashing"
    assert model.model_name == "feature-hash-128d"


def test_hashing_rejects_tiny_dim() -> None:
    with pytest.raises(ValueError):
        HashingEmbeddingModel(dim=4)


async def test_hashing_satisfies_protocol() -> None:
    assert isinstance(HashingEmbeddingModel(), EmbeddingModel)


def _transport(
    payload: dict, requests: list[httpx.Request]
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


async def test_local_openai_format() -> None:
    requests: list[httpx.Request] = []
    payload = {
        "data": [
            {"index": 1, "embedding": [0.4, 0.5, 0.6]},
            {"index": 0, "embedding": [0.1, 0.2, 0.3]},
        ]
    }
    model = LocalEmbeddingModel(
        base_url="http://127.0.0.1:11434/v1/",
        model_name="emb-test",
        transport=_transport(payload, requests),
    )

    vectors = await model.embed(["hello world", "second text"])

    assert vectors == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert model.provider == "local"
    assert model.model_name == "emb-test"
    assert len(requests) == 1
    assert requests[0].url.path == "/v1/embeddings"
    body = json.loads(requests[0].content)
    assert body == {"model": "emb-test", "input": ["hello world", "second text"]}


async def test_local_ollama_native_format() -> None:
    requests: list[httpx.Request] = []
    payload = {"embeddings": [[0.1, 0.2], [0.3, 0.4]]}
    model = LocalEmbeddingModel(
        base_url="http://127.0.0.1:11434/v1",
        transport=_transport(payload, requests),
    )

    vectors = await model.embed(["a", "b"])

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]


async def test_local_count_mismatch_raises() -> None:
    payload = {"data": [{"index": 0, "embedding": [0.1]}]}
    model = LocalEmbeddingModel(
        base_url="http://127.0.0.1:11434/v1",
        transport=_transport(payload, []),
    )

    with pytest.raises(RuntimeError):
        await model.embed(["one", "two"])


async def test_local_empty_input_skips_request() -> None:
    requests: list[httpx.Request] = []
    model = LocalEmbeddingModel(
        base_url="http://127.0.0.1:11434/v1",
        transport=_transport({"data": []}, requests),
    )

    assert await model.embed([]) == []
    assert requests == []

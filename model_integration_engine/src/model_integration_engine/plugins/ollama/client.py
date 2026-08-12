"""Documented Ollama HTTP API client with an injectable transport.

The client contains no model-family behavior. Tests provide a deterministic
transport; the stdlib transport is available for separately authorized live use.
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

from ...domain import JSONValue


class OllamaClientError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code


class OllamaUnavailableError(OllamaClientError):
    pass


class OllamaProtocolError(OllamaClientError):
    pass


class JsonTransport(Protocol):
    async def request_json(
        self,
        method: str,
        url: str,
        body: Mapping[str, JSONValue] | None = None,
        *,
        timeout_seconds: float,
    ) -> Mapping[str, JSONValue]: ...

    def stream_ndjson(
        self,
        method: str,
        url: str,
        body: Mapping[str, JSONValue],
        *,
        timeout_seconds: float,
    ) -> AsyncIterator[Mapping[str, JSONValue]]: ...


@dataclass(slots=True)
class StdlibJsonTransport:
    """No-dependency live transport.

    NDJSON is read in a worker thread and yielded after parsing. This validates
    protocol chunking but is not intended for production low-latency streaming.
    """

    user_agent: str = "model-integration-engine/0.2.0"

    async def request_json(
        self,
        method: str,
        url: str,
        body: Mapping[str, JSONValue] | None = None,
        *,
        timeout_seconds: float,
    ) -> Mapping[str, JSONValue]:
        return await asyncio.to_thread(
            self._request_json_sync, method, url, body, timeout_seconds
        )

    def _request_json_sync(
        self,
        method: str,
        url: str,
        body: Mapping[str, JSONValue] | None,
        timeout_seconds: float,
    ) -> Mapping[str, JSONValue]:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            method=method,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": self.user_agent,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise OllamaClientError(
                "OLLAMA_HTTP_ERROR",
                f"Ollama returned HTTP {exc.code}",
                retryable=500 <= exc.code < 600,
                status_code=exc.code,
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise OllamaUnavailableError(
                "RUNTIME_UNREACHABLE",
                "Ollama endpoint is unavailable",
                retryable=True,
            ) from exc
        return _parse_object(raw, url)

    async def _read_ndjson(
        self,
        method: str,
        url: str,
        body: Mapping[str, JSONValue],
        timeout_seconds: float,
    ) -> list[Mapping[str, JSONValue]]:
        return await asyncio.to_thread(
            self._read_ndjson_sync, method, url, body, timeout_seconds
        )

    def _read_ndjson_sync(
        self,
        method: str,
        url: str,
        body: Mapping[str, JSONValue],
        timeout_seconds: float,
    ) -> list[Mapping[str, JSONValue]]:
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            method=method,
            headers={
                "Accept": "application/x-ndjson",
                "Content-Type": "application/json",
                "User-Agent": self.user_agent,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                lines = response.readlines()
        except urllib.error.HTTPError as exc:
            raise OllamaClientError(
                "OLLAMA_HTTP_ERROR",
                f"Ollama returned HTTP {exc.code}",
                retryable=500 <= exc.code < 600,
                status_code=exc.code,
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise OllamaUnavailableError(
                "RUNTIME_UNREACHABLE",
                "Ollama endpoint is unavailable",
                retryable=True,
            ) from exc

        events: list[Mapping[str, JSONValue]] = []
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            events.append(_parse_object(line, f"{url}#line={index + 1}"))
        return events

    async def stream_ndjson(
        self,
        method: str,
        url: str,
        body: Mapping[str, JSONValue],
        *,
        timeout_seconds: float,
    ) -> AsyncIterator[Mapping[str, JSONValue]]:
        events = await self._read_ndjson(method, url, body, timeout_seconds)
        for event in events:
            yield event


def _parse_object(raw: bytes, source: str) -> Mapping[str, JSONValue]:
    try:
        value: Any = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OllamaProtocolError(
            "MALFORMED_RUNTIME_RESPONSE",
            f"Ollama returned malformed JSON from {source}",
            retryable=False,
        ) from exc
    if not isinstance(value, dict):
        raise OllamaProtocolError(
            "MALFORMED_RUNTIME_RESPONSE",
            f"Ollama response from {source} must be an object",
            retryable=False,
        )
    return value


def normalize_endpoint(endpoint: str) -> str:
    candidate = endpoint.strip().rstrip("/")
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Ollama endpoint must be an absolute http(s) URL")
    if parsed.query or parsed.fragment:
        raise ValueError("Ollama endpoint must not contain query or fragment")
    return candidate


@dataclass(slots=True)
class OllamaClient:
    endpoint: str
    transport: JsonTransport
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        self.endpoint = normalize_endpoint(self.endpoint)
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def _url(self, path: str) -> str:
        return f"{self.endpoint}{path}"

    async def version(self) -> Mapping[str, JSONValue]:
        response = await self.transport.request_json(
            "GET", self._url("/api/version"), timeout_seconds=self.timeout_seconds
        )
        if not isinstance(response.get("version"), str) or not response["version"]:
            raise OllamaProtocolError(
                "MALFORMED_VERSION_RESPONSE",
                "Ollama version response requires a non-empty string 'version'",
                retryable=False,
            )
        return response

    async def tags(self) -> Mapping[str, JSONValue]:
        response = await self.transport.request_json(
            "GET", self._url("/api/tags"), timeout_seconds=self.timeout_seconds
        )
        models = response.get("models")
        if not isinstance(models, list):
            raise OllamaProtocolError(
                "MALFORMED_MODEL_LIST",
                "Ollama tags response requires a 'models' array",
                retryable=False,
            )
        if not all(isinstance(item, dict) for item in models):
            raise OllamaProtocolError(
                "MALFORMED_MODEL_LIST",
                "Every Ollama model summary must be an object",
                retryable=False,
            )
        return response

    async def show(
        self, model_reference: str, *, verbose: bool = False
    ) -> Mapping[str, JSONValue]:
        if not model_reference.strip():
            raise ValueError("model_reference must be non-empty")
        return await self.transport.request_json(
            "POST",
            self._url("/api/show"),
            {"model": model_reference, "verbose": verbose},
            timeout_seconds=self.timeout_seconds,
        )

    async def chat(
        self, body: Mapping[str, JSONValue]
    ) -> Mapping[str, JSONValue]:
        request_body = dict(body)
        request_body["stream"] = False
        return await self.transport.request_json(
            "POST",
            self._url("/api/chat"),
            request_body,
            timeout_seconds=self.timeout_seconds,
        )

    def chat_stream(
        self, body: Mapping[str, JSONValue]
    ) -> AsyncIterator[Mapping[str, JSONValue]]:
        request_body = dict(body)
        request_body["stream"] = True
        return self.transport.stream_ndjson(
            "POST",
            self._url("/api/chat"),
            request_body,
            timeout_seconds=self.timeout_seconds,
        )

"""Runtime plugin registry — serving/quantization choices behind one contract.

Phase 4: TurboQuant, vLLM, llama.cpp, and Ollama become *options* behind the
RuntimePlugin registry, so the serving/quantization choice never touches
application code. The registry is advisory by design: the router consults it
to log/report which runtime backs local inference, but a missing runtime
never breaks model construction (offline-first guarantee).

Availability probes are short, failure-tolerant, and stdlib-only.
"""

from __future__ import annotations

import os
import urllib.request
from enum import StrEnum
from typing import Protocol, runtime_checkable

from sage.logging import get_logger

log = get_logger(__name__)


class RuntimeKind(StrEnum):
    SERVING = "serving"
    QUANTIZATION = "quantization"


@runtime_checkable
class RuntimePlugin(Protocol):
    """One serving/quantization option. Register, never hardcode."""

    @property
    def name(self) -> str: ...

    @property
    def kind(self) -> RuntimeKind: ...

    def is_available(self) -> bool: ...

    def describe(self) -> str: ...


def _probe(url: str, *, timeout: float = 0.75) -> bool:
    """Best-effort availability probe; any failure means 'not available'."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 500
    except Exception:
        return False


class OllamaRuntime:
    """Local Ollama server (default ``http://127.0.0.1:11434``)."""

    name = "ollama"
    kind = RuntimeKind.SERVING

    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = (
            base_url
            or os.environ.get("SAGE_OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        ).rstrip("/")

    def is_available(self) -> bool:
        return _probe(f"{self._base_url}/api/tags")

    def describe(self) -> str:
        return f"Ollama local server at {self._base_url}"


class LlamaCppRuntime:
    """llama.cpp server (default port 8080, override with LLAMA_CPP_BASE_URL)."""

    name = "llama.cpp"
    kind = RuntimeKind.SERVING

    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = (
            base_url or os.environ.get("LLAMA_CPP_BASE_URL", "http://127.0.0.1:8080")
        ).rstrip("/")

    def is_available(self) -> bool:
        return _probe(f"{self._base_url}/health")

    def describe(self) -> str:
        return f"llama.cpp server at {self._base_url}"


class VllmRuntime:
    """vLLM OpenAI-compatible server (override with VLLM_BASE_URL)."""

    name = "vllm"
    kind = RuntimeKind.SERVING

    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = (
            base_url or os.environ.get("VLLM_BASE_URL", "http://127.0.0.1:8000")
        ).rstrip("/")

    def is_available(self) -> bool:
        return _probe(f"{self._base_url}/v1/models")

    def describe(self) -> str:
        return f"vLLM OpenAI-compatible server at {self._base_url}"


class TurboQuantRuntime:
    """TurboQuant-style quantization.

    Available when an installed package advertises it, or when the user
    explicitly opts in via SAGE_TURBOQUANT=1 (e.g. a planned adapter is
    pending). Never available silently.
    """

    name = "turboquant"
    kind = RuntimeKind.QUANTIZATION

    def is_available(self) -> bool:
        if os.environ.get("SAGE_TURBOQUANT", "").lower() in {"1", "true", "yes"}:
            return True
        try:  # pragma: no cover - depends on environment
            import turboquant  # noqa: F401

            return True
        except ImportError:
            return False

    def describe(self) -> str:
        return "TurboQuant quantization adapter (opt-in)"


class RuntimeRegistry:
    """Registry of runtime plugins; consult, never hardcode."""

    def __init__(self) -> None:
        self._plugins: dict[str, RuntimePlugin] = {}

    def register(self, plugin: RuntimePlugin) -> None:
        if plugin.name in self._plugins:
            raise ValueError(f"runtime already registered: {plugin.name}")
        self._plugins[plugin.name] = plugin
        log.debug("runtime.registered", name=plugin.name, kind=plugin.kind.value)

    def get(self, name: str) -> RuntimePlugin | None:
        return self._plugins.get(name)

    def list(self, kind: RuntimeKind | None = None) -> list[RuntimePlugin]:
        plugins = list(self._plugins.values())
        if kind is None:
            return plugins
        return [p for p in plugins if p.kind == kind]

    def available(self, kind: RuntimeKind | None = None) -> list[RuntimePlugin]:
        return [p for p in self.list(kind) if p.is_available()]

    def select(self, kind: RuntimeKind) -> RuntimePlugin | None:
        """First available runtime of ``kind`` (registration order)."""
        for plugin in self.list(kind):
            try:
                if plugin.is_available():
                    return plugin
            except Exception:
                log.exception("runtime.probe_failed", name=plugin.name)
        return None

    def names(self) -> list[str]:
        return list(self._plugins)


def build_default_registry() -> RuntimeRegistry:
    """Registry preloaded with the four planned runtime options."""
    registry = RuntimeRegistry()
    registry.register(OllamaRuntime())
    registry.register(LlamaCppRuntime())
    registry.register(VllmRuntime())
    registry.register(TurboQuantRuntime())
    return registry

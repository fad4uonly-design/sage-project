"""Ollama runtime plugin wiring for generic discovery/inspection/adapter ports."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from ..domain import PluginDescriptor, TrustState
from ..plugins.ollama.adapter import GenericOllamaAdapter
from ..plugins.ollama.client import JsonTransport, OllamaClient, normalize_endpoint
from ..plugins.ollama.discovery import OllamaDiscoveryProvider
from ..plugins.ollama.inspection import OllamaModelInspector
from .base import RuntimePluginDescriptor


@dataclass(slots=True)
class OllamaRuntimePlugin:
    transport: JsonTransport
    timeout_seconds: float = 10.0

    @property
    def descriptor_v3(self) -> RuntimePluginDescriptor:
        return RuntimePluginDescriptor(
            plugin=PluginDescriptor(
                plugin_id="mie.runtime.ollama",
                plugin_version="0.3.0",
                contract_version="runtime-plugin-0.3.0",
                operations=("discover", "inspect", "infer", "stream"),
                supported_subjects=("RUNTIME", "DEPLOYMENT"),
                required_permissions=("network:configured-runtime-endpoint",),
                trust_state=TrustState.TRUSTED_EXISTING,
            ),
            runtime_kind="ollama",
            locator_schemes=("http", "https"),
            protocols=("ollama-native-http",),
            discovery_operations=("version", "list_models", "show_model"),
            inference_operations=("chat", "stream", "tools", "structured_output"),
            local_first=True,
        )

    def supports_locator(self, locator: str) -> bool:
        try:
            normalized = normalize_endpoint(locator)
        except ValueError:
            return False
        parsed = urlparse(normalized)
        # HTTP is shared by many future runtimes; explicit runtime_kind policy is
        # expected when more HTTP plugins are registered.
        return parsed.scheme in self.descriptor_v3.locator_schemes

    def _client(self, locator: str) -> OllamaClient:
        return OllamaClient(
            normalize_endpoint(locator), self.transport, self.timeout_seconds
        )

    def create_discovery_provider(self, locator: str) -> OllamaDiscoveryProvider:
        return OllamaDiscoveryProvider(self._client(locator))

    def create_inspector(self, locator: str) -> OllamaModelInspector:
        return OllamaModelInspector(self._client(locator))

    def create_adapter(self, locator: str, config) -> GenericOllamaAdapter:
        return GenericOllamaAdapter(self._client(locator), config)

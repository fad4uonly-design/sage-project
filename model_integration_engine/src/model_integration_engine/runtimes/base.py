"""Generic runtime-plugin extension contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

from ..domain import PluginDescriptor


@dataclass(frozen=True, slots=True)
class RuntimePluginDescriptor:
    plugin: PluginDescriptor
    runtime_kind: str
    locator_schemes: tuple[str, ...]
    protocols: tuple[str, ...]
    discovery_operations: tuple[str, ...]
    inference_operations: tuple[str, ...]
    local_first: bool


class RuntimePlugin(Protocol):
    descriptor_v3: RuntimePluginDescriptor

    def supports_locator(self, locator: str) -> bool: ...

    def create_discovery_provider(self, locator: str): ...

    def create_inspector(self, locator: str): ...

    def create_adapter(self, locator: str, config): ...


def locator_scheme(locator: str) -> str:
    parsed = urlparse(locator)
    return parsed.scheme.lower()

"""Deterministic runtime-plugin registration and selection."""

from __future__ import annotations

from dataclasses import dataclass, field

from .base import RuntimePlugin


class RuntimePluginError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class RuntimePluginRegistry:
    _plugins: dict[str, RuntimePlugin] = field(default_factory=dict)

    def register(self, plugin: RuntimePlugin) -> None:
        plugin_id = plugin.descriptor_v3.plugin.plugin_id
        if plugin_id in self._plugins:
            raise RuntimePluginError(
                "RUNTIME_PLUGIN_DUPLICATE", f"Duplicate runtime plugin {plugin_id}"
            )
        self._plugins[plugin_id] = plugin

    def plugins(self) -> tuple[RuntimePlugin, ...]:
        return tuple(self._plugins[key] for key in sorted(self._plugins))

    def select(
        self, locator: str, *, runtime_kind: str | None = None
    ) -> RuntimePlugin:
        matches = [
            plugin
            for plugin in self._plugins.values()
            if (runtime_kind is None or plugin.descriptor_v3.runtime_kind == runtime_kind)
            and plugin.supports_locator(locator)
        ]
        if not matches:
            raise RuntimePluginError(
                "RUNTIME_PLUGIN_NOT_FOUND",
                f"No runtime plugin supports locator {locator!r}",
            )
        if len(matches) > 1:
            raise RuntimePluginError(
                "RUNTIME_PLUGIN_AMBIGUOUS",
                "Multiple runtime plugins match; specify runtime_kind/plugin policy",
            )
        return matches[0]

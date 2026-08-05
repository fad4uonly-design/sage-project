"""Plugin discovery and lifecycle manager."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from sage.core.container import Container
from sage.logging import get_logger
from sage.plugins.interfaces import Plugin
from sage.plugins.manifest import PluginManifest

log = get_logger(__name__)


class PluginManager:
    def __init__(self, container: Container) -> None:
        self._container = container
        self._plugins: dict[str, Plugin] = {}

    @property
    def loaded(self) -> list[str]:
        return list(self._plugins.keys())

    async def load_from_directories(self, directories: list[str]) -> list[str]:
        loaded: list[str] = []
        for d in directories:
            path = Path(d).expanduser()
            if not path.is_dir():
                log.debug("plugins.dir_missing", path=str(path))
                continue
            for child in sorted(path.iterdir()):
                if not child.is_dir():
                    continue
                manifest_path = child / "plugin.yaml"
                if not manifest_path.is_file():
                    manifest_path = child / "plugin.json"
                if not manifest_path.is_file():
                    continue
                try:
                    plugin = await self._load_plugin_dir(child, manifest_path)
                    if plugin is not None:
                        loaded.append(plugin.manifest.id)
                except Exception:
                    log.exception("plugins.load_failed", path=str(child))
        return loaded

    async def _load_plugin_dir(self, directory: Path, manifest_path: Path) -> Plugin | None:
        raw = manifest_path.read_text(encoding="utf-8")
        data: dict[str, Any]
        if manifest_path.suffix == ".json":
            data = json.loads(raw)
        else:
            data = yaml.safe_load(raw) or {}
        manifest = PluginManifest.model_validate(data)
        if not manifest.enabled:
            log.info("plugins.skipped_disabled", id=manifest.id)
            return None

        # entrypoint format: module_file:ClassName  (module_file relative, without .py)
        module_part, _, class_name = manifest.entrypoint.partition(":")
        class_name = class_name or "Plugin"
        module_file = directory / f"{module_part.replace('.', '/')}.py"
        if not module_file.is_file():
            # try plugin.py default
            module_file = directory / "plugin.py"
        if not module_file.is_file():
            raise FileNotFoundError(f"Plugin entry not found in {directory}")

        mod_name = f"sage_plugin_{manifest.id.replace('-', '_')}"
        spec = importlib.util.spec_from_file_location(mod_name, module_file)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load plugin module: {module_file}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        spec.loader.exec_module(module)
        cls = getattr(module, class_name)
        plugin: Plugin = cls() if not isinstance(cls, type) else cls()  # type: ignore[assignment]
        # Ensure manifest is available
        if not hasattr(plugin, "manifest"):
            raise TypeError(f"Plugin {manifest.id} missing manifest property")

        await plugin.on_load(self._container)
        self._plugins[manifest.id] = plugin
        log.info("plugins.loaded", id=manifest.id, version=manifest.version)
        return plugin

    async def unload_all(self) -> None:
        for pid, plugin in list(self._plugins.items()):
            try:
                await plugin.on_unload()
            except Exception:
                log.exception("plugins.unload_failed", id=pid)
        self._plugins.clear()

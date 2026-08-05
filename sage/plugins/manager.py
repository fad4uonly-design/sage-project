"""Plugin discovery and lifecycle manager with permission requests."""

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
        self._enabled: dict[str, bool] = {}

    @property
    def loaded(self) -> list[str]:
        return list(self._plugins.keys())

    def is_enabled(self, plugin_id: str) -> bool:
        return self._enabled.get(plugin_id, False)

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

        # Permission requests before load
        await self._request_permissions(manifest)

        module_part, _, class_name = manifest.entrypoint.partition(":")
        class_name = class_name or "Plugin"
        module_file = directory / f"{module_part.replace('.', '/')}.py"
        if not module_file.is_file():
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
        if not hasattr(plugin, "manifest"):
            raise TypeError(f"Plugin {manifest.id} missing manifest property")

        await plugin.on_load(self._container)
        self._plugins[manifest.id] = plugin
        self._enabled[manifest.id] = True
        log.info("plugins.loaded", id=manifest.id, version=manifest.version)
        return plugin

    async def _request_permissions(self, manifest: PluginManifest) -> None:
        if not manifest.permissions:
            return
        from sage.permissions.interfaces import PermissionManager
        from sage.permissions.models import PrincipalType

        pm = self._container.try_resolve(PermissionManager)  # type: ignore[type-abstract]
        if pm is None:
            log.warning("plugins.permissions_unavailable", plugin=manifest.id)
            return
        grants = await pm.request(
            manifest.id,
            manifest.permissions,
            principal_type=PrincipalType.PLUGIN,
            auto_approve_safe=True,
        )
        pending = [g.permission.value for g in grants if not g.granted]
        if pending:
            log.warning(
                "plugins.permissions_pending",
                plugin=manifest.id,
                pending=pending,
                msg="Dangerous permissions require explicit user grant via PermissionManager.grant",
            )

    async def enable(self, plugin_id: str) -> bool:
        if plugin_id not in self._plugins:
            return False
        self._enabled[plugin_id] = True
        return True

    async def disable(self, plugin_id: str) -> bool:
        if plugin_id not in self._plugins:
            return False
        self._enabled[plugin_id] = False
        log.info("plugins.disabled", id=plugin_id)
        return True

    async def unload_all(self) -> None:
        for pid, plugin in list(self._plugins.items()):
            try:
                await plugin.on_unload()
            except Exception:
                log.exception("plugins.unload_failed", id=pid)
        self._plugins.clear()
        self._enabled.clear()

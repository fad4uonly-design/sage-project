"""Registry of loaded SAGE modules."""

from __future__ import annotations

from sage.core.module import SageModule
from sage.logging import get_logger

log = get_logger(__name__)


class ModuleRegistry:
    """Ordered registry preserving initialization order."""

    def __init__(self) -> None:
        self._modules: dict[str, SageModule] = {}
        self._order: list[str] = []

    def register(self, module: SageModule) -> None:
        if module.name in self._modules:
            raise ValueError(f"Module already registered: {module.name}")
        self._modules[module.name] = module
        self._order.append(module.name)
        log.debug("registry.register", module=module.name)

    def get(self, name: str) -> SageModule | None:
        return self._modules.get(name)

    def require(self, name: str) -> SageModule:
        mod = self._modules.get(name)
        if mod is None:
            raise KeyError(f"Module not found: {name}")
        return mod

    def all(self) -> list[SageModule]:
        return [self._modules[n] for n in self._order]

    def names(self) -> list[str]:
        return list(self._order)

    def __contains__(self, name: str) -> bool:
        return name in self._modules

    def __len__(self) -> int:
        return len(self._modules)

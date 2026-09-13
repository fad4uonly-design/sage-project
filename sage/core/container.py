"""
Lightweight dependency-injection container.

Services are registered by type (and optional name) and resolved lazily.
This is intentionally small — no third-party DI framework required.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar, cast

T = TypeVar("T")


class ContainerError(Exception):
    """Raised when registration or resolution fails."""


class Container:
    """Simple service locator / DI container."""

    def __init__(self) -> None:
        self._singletons: dict[str, Any] = {}
        self._factories: dict[str, Callable[[Container], Any]] = {}
        self._resolving: set[str] = set()

    @staticmethod
    def _key(service_type: type | str, name: str | None = None) -> str:
        base = service_type if isinstance(service_type, str) else f"{service_type.__module__}.{service_type.__qualname__}"
        return f"{base}::{name or 'default'}"

    def register(
        self,
        service_type: type[T] | str,
        instance: T | None = None,
        *,
        factory: Callable[[Container], T] | None = None,
        name: str | None = None,
    ) -> None:
        """
        Register a service.

        Provide either `instance` (eager singleton) or `factory` (lazy singleton).
        """
        if instance is None and factory is None:
            raise ContainerError("Must provide instance or factory")
        if instance is not None and factory is not None:
            raise ContainerError("Provide only one of instance or factory")

        key = self._key(service_type, name)
        if instance is not None:
            self._singletons[key] = instance
            self._factories.pop(key, None)
        else:
            assert factory is not None
            self._factories[key] = factory
            self._singletons.pop(key, None)

    def register_instance(self, service_type: type[T] | str, instance: T, *, name: str | None = None) -> None:
        self.register(service_type, instance=instance, name=name)

    def register_factory(
        self,
        service_type: type[T] | str,
        factory: Callable[[Container], T],
        *,
        name: str | None = None,
    ) -> None:
        self.register(service_type, factory=factory, name=name)

    def resolve(self, service_type: type[T] | str, *, name: str | None = None) -> T:
        key = self._key(service_type, name)

        if key in self._singletons:
            return cast(T, self._singletons[key])

        if key in self._factories:
            if key in self._resolving:
                raise ContainerError(f"Circular dependency while resolving {key}")
            self._resolving.add(key)
            try:
                instance = self._factories[key](self)
                self._singletons[key] = instance
                return cast(T, instance)
            finally:
                self._resolving.discard(key)

        type_name = service_type if isinstance(service_type, str) else service_type.__qualname__
        raise ContainerError(f"Service not registered: {type_name}" + (f" (name={name})" if name else ""))

    def try_resolve(self, service_type: type[T] | str, *, name: str | None = None) -> T | None:
        try:
            return self.resolve(service_type, name=name)
        except ContainerError:
            return None

    def has(self, service_type: type | str, *, name: str | None = None) -> bool:
        key = self._key(service_type, name)
        return key in self._singletons or key in self._factories

    def keys(self) -> list[str]:
        return sorted(set(self._singletons) | set(self._factories))

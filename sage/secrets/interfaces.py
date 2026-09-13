"""Secrets manager protocol."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SecretsManager(Protocol):
    async def set_secret(
        self, key: str, value: str, *, metadata: dict[str, Any] | None = None
    ) -> None: ...

    async def get_secret(self, key: str) -> str | None: ...

    async def delete_secret(self, key: str) -> bool: ...

    async def list_keys(self) -> list[str]: ...

    async def rotate(self, key: str, new_value: str) -> None: ...

    async def has(self, key: str) -> bool: ...

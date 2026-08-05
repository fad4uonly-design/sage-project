"""Permission manager protocol."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from sage.permissions.models import Permission, PermissionGrant, PrincipalType


@runtime_checkable
class PermissionManager(Protocol):
    async def grant(
        self,
        principal: str,
        permission: Permission | str,
        *,
        principal_type: PrincipalType = PrincipalType.PLUGIN,
        reason: str = "",
        granted_by: str = "user",
    ) -> PermissionGrant: ...

    async def revoke(self, principal: str, permission: Permission | str) -> bool: ...

    async def check(self, principal: str, permission: Permission | str) -> bool: ...

    async def require(self, principal: str, permission: Permission | str) -> None: ...

    async def list_grants(self, principal: str | None = None) -> list[PermissionGrant]: ...

    async def request(
        self,
        principal: str,
        permissions: Iterable[Permission | str],
        *,
        principal_type: PrincipalType = PrincipalType.PLUGIN,
        auto_approve_safe: bool = True,
    ) -> list[PermissionGrant]: ...

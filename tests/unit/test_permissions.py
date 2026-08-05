"""Permission manager tests."""

from __future__ import annotations

import pytest

from sage.core.engine import SageEngine
from sage.permissions.interfaces import PermissionManager
from sage.permissions.models import Permission, PermissionDenied, PrincipalType


@pytest.mark.asyncio
async def test_grant_check_revoke(engine: SageEngine) -> None:
    pm = engine.container.resolve(PermissionManager)  # type: ignore[type-abstract]
    await pm.grant(
        "plugin.demo",
        Permission.FILESYSTEM_READ,
        principal_type=PrincipalType.PLUGIN,
    )
    assert await pm.check("plugin.demo", Permission.FILESYSTEM_READ)
    await pm.require("plugin.demo", Permission.FILESYSTEM_READ)
    assert await pm.revoke("plugin.demo", Permission.FILESYSTEM_READ)
    assert not await pm.check("plugin.demo", Permission.FILESYSTEM_READ)


@pytest.mark.asyncio
async def test_dangerous_pending(engine: SageEngine) -> None:
    pm = engine.container.resolve(PermissionManager)  # type: ignore[type-abstract]
    grants = await pm.request("plugin.risky", [Permission.SHELL, Permission.MEMORY_READ])
    by_perm = {g.permission: g for g in grants}
    assert by_perm[Permission.SHELL].granted is False
    assert by_perm[Permission.MEMORY_READ].granted is True

    with pytest.raises(PermissionDenied):
        await pm.require("plugin.risky", Permission.SHELL)


@pytest.mark.asyncio
async def test_system_principal_always_allowed(engine: SageEngine) -> None:
    pm = engine.container.resolve(PermissionManager)  # type: ignore[type-abstract]
    assert await pm.check("system", Permission.SHELL)

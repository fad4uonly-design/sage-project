"""Permission manager implementation."""

from __future__ import annotations

from collections.abc import Iterable

from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.db.connection import Database
from sage.db.repository import BaseRepository
from sage.events.bus import EventBus
from sage.events.events import Event
from sage.logging import get_logger
from sage.permissions.interfaces import PermissionManager
from sage.permissions.models import (
    DANGEROUS_PERMISSIONS,
    Permission,
    PermissionDenied,
    PermissionGrant,
    PrincipalType,
)
from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso

log = get_logger(__name__)


def _as_permission(permission: Permission | str) -> Permission:
    if isinstance(permission, Permission):
        return permission
    return Permission(permission)


class DefaultPermissionManager(BaseRepository):
    def __init__(self, db: Database, events: EventBus | None = None) -> None:
        super().__init__(db)
        self._events = events

    async def grant(
        self,
        principal: str,
        permission: Permission | str,
        *,
        principal_type: PrincipalType = PrincipalType.PLUGIN,
        reason: str = "",
        granted_by: str = "user",
    ) -> PermissionGrant:
        perm = _as_permission(permission)
        now = utcnow_iso()
        grant = PermissionGrant(
            principal=principal,
            principal_type=principal_type,
            permission=perm,
            granted=True,
            reason=reason or None,
            granted_by=granted_by,
            created_at=now,
            updated_at=now,
        )
        await self.db.execute(
            """
            INSERT INTO permission_grants
                (id, principal, principal_type, permission, granted, reason, granted_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)
            ON CONFLICT(principal, permission) DO UPDATE SET
                granted = 1,
                reason = excluded.reason,
                granted_by = excluded.granted_by,
                updated_at = excluded.updated_at
            """,
            (
                grant.id,
                grant.principal,
                grant.principal_type.value,
                grant.permission.value,
                grant.reason,
                grant.granted_by,
                grant.created_at,
                grant.updated_at,
            ),
        )
        log.info(
            "permissions.granted",
            principal=principal,
            permission=perm.value,
            by=granted_by,
        )
        if self._events:
            await self._events.publish(
                Event(
                    type="permissions.granted",
                    payload={"principal": principal, "permission": perm.value},
                    source="permissions",
                )
            )
        return grant

    async def revoke(self, principal: str, permission: Permission | str) -> bool:
        perm = _as_permission(permission)
        cur = await self.db.execute(
            """
            UPDATE permission_grants
            SET granted = 0, updated_at = ?
            WHERE principal = ? AND permission = ?
            """,
            (utcnow_iso(), principal, perm.value),
        )
        ok = (cur.rowcount or 0) > 0
        if ok:
            log.info("permissions.revoked", principal=principal, permission=perm.value)
            if self._events:
                await self._events.publish(
                    Event(
                        type="permissions.revoked",
                        payload={"principal": principal, "permission": perm.value},
                        source="permissions",
                    )
                )
        return ok

    async def check(self, principal: str, permission: Permission | str) -> bool:
        if principal in {"system", "core", "sage"}:
            return True
        perm = _as_permission(permission)
        row = await self.db.fetchone(
            """
            SELECT granted FROM permission_grants
            WHERE principal = ? AND permission = ?
            """,
            (principal, perm.value),
        )
        return bool(row and row["granted"])

    async def require(self, principal: str, permission: Permission | str) -> None:
        if not await self.check(principal, permission):
            raise PermissionDenied(principal, _as_permission(permission))

    async def list_grants(self, principal: str | None = None) -> list[PermissionGrant]:
        if principal:
            rows = await self.db.fetchall(
                "SELECT * FROM permission_grants WHERE principal = ? ORDER BY permission",
                (principal,),
            )
        else:
            rows = await self.db.fetchall(
                "SELECT * FROM permission_grants ORDER BY principal, permission"
            )
        return [self._row_to_grant(r) for r in rows]

    async def request(
        self,
        principal: str,
        permissions: Iterable[Permission | str],
        *,
        principal_type: PrincipalType = PrincipalType.PLUGIN,
        auto_approve_safe: bool = True,
    ) -> list[PermissionGrant]:
        """
        Register permission requests.

        Safe permissions may be auto-approved; dangerous ones are stored as denied
        until the user explicitly grants them.
        """
        results: list[PermissionGrant] = []
        for p in permissions:
            perm = _as_permission(p)
            existing = await self.check(principal, perm)
            if existing:
                results.append(
                    PermissionGrant(
                        principal=principal,
                        principal_type=principal_type,
                        permission=perm,
                        granted=True,
                        reason="already_granted",
                    )
                )
                continue

            is_dangerous = perm in DANGEROUS_PERMISSIONS
            approve = auto_approve_safe and not is_dangerous
            now = utcnow_iso()
            grant = PermissionGrant(
                id=new_id("perm"),
                principal=principal,
                principal_type=principal_type,
                permission=perm,
                granted=approve,
                reason="auto_safe" if approve else "pending_user_approval",
                granted_by="system" if approve else "pending",
                created_at=now,
                updated_at=now,
            )
            await self.db.execute(
                """
                INSERT INTO permission_grants
                    (id, principal, principal_type, permission, granted, reason, granted_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(principal, permission) DO NOTHING
                """,
                (
                    grant.id,
                    grant.principal,
                    grant.principal_type.value,
                    grant.permission.value,
                    1 if grant.granted else 0,
                    grant.reason,
                    grant.granted_by,
                    grant.created_at,
                    grant.updated_at,
                ),
            )
            if is_dangerous and not approve:
                log.warning(
                    "permissions.pending",
                    principal=principal,
                    permission=perm.value,
                    msg="Dangerous permission requires explicit user grant",
                )
            results.append(grant)
        return results

    def _row_to_grant(self, row: object) -> PermissionGrant:
        r = row  # aiosqlite.Row
        return PermissionGrant(
            id=r["id"],  # type: ignore[index]
            principal=r["principal"],  # type: ignore[index]
            principal_type=PrincipalType(r["principal_type"]),  # type: ignore[index]
            permission=Permission(r["permission"]),  # type: ignore[index]
            granted=bool(r["granted"]),  # type: ignore[index]
            reason=r["reason"],  # type: ignore[index]
            granted_by=r["granted_by"],  # type: ignore[index]
            created_at=r["created_at"],  # type: ignore[index]
            updated_at=r["updated_at"],  # type: ignore[index]
        )

    async def count_grants(self) -> int:
        return int(await self.db.scalar("SELECT COUNT(*) FROM permission_grants") or 0)


class PermissionsModule(BaseModule):
    name = "permissions"
    version = "0.1.1"
    is_critical = True

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._mgr: DefaultPermissionManager | None = None

    async def _on_initialize(self) -> None:
        db = self.container.resolve(Database)
        events = self.container.try_resolve(EventBus)  # type: ignore[type-abstract]
        self._mgr = DefaultPermissionManager(db, events)
        self.container.register_instance(PermissionManager, self._mgr)  # type: ignore[type-abstract]
        self.container.register_instance(DefaultPermissionManager, self._mgr)

        # Core / automation principals trusted for safe ops
        for principal in ("core", "automation", "cli"):
            for perm in (
                Permission.MEMORY_READ,
                Permission.MEMORY_WRITE,
                Permission.TOOLS_INVOKE,
                Permission.AGENTS_DISPATCH,
                Permission.NOTIFICATIONS,
                Permission.FILESYSTEM_READ,
            ):
                await self._mgr.grant(
                    principal,
                    perm,
                    principal_type=PrincipalType.SYSTEM,
                    granted_by="bootstrap",
                )

    async def _on_health(self) -> HealthStatus | None:
        if self._mgr is None:
            return HealthStatus.unhealthy(self.name, "not initialized", critical=True)
        n = await self._mgr.count_grants()
        return HealthStatus.healthy(self.name, "ok", grants=n)

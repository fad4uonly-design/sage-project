"""Approval Engine implementation."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from sage.approval.models import (
    ApprovalDecision,
    ApprovalLevel,
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalStatus,
)
from sage.db.connection import Database
from sage.db.repository import BaseRepository
from sage.events.bus import EventBus
from sage.events.events import Event
from sage.logging import get_logger
from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso

log = get_logger(__name__)

# Defaults for sensitive resources when no policy row exists
_DEFAULT_LEVELS: dict[tuple[str, str], ApprovalLevel] = {
    ("tool", "shell"): ApprovalLevel.ALWAYS_ASK,
    ("tool", "http_request"): ApprovalLevel.ASK_ONCE,
    ("tool", "write_file"): ApprovalLevel.ASK_ONCE,
    ("tool", "delete_file"): ApprovalLevel.ALWAYS_ASK,
    ("tool", "git"): ApprovalLevel.ASK_ONCE,
    ("filesystem", "write"): ApprovalLevel.ASK_ONCE,
    ("filesystem", "delete"): ApprovalLevel.ALWAYS_ASK,
}


@runtime_checkable
class ApprovalEngine(Protocol):
    async def set_policy(
        self,
        resource_type: str,
        resource_id: str,
        level: ApprovalLevel | str,
        *,
        principal: str | None = None,
    ) -> ApprovalPolicy: ...

    async def get_level(
        self, resource_type: str, resource_id: str, *, principal: str | None = None
    ) -> ApprovalLevel: ...

    async def check(
        self,
        resource_type: str,
        resource_id: str,
        action: str,
        *,
        principal: str = "user",
        payload: dict[str, Any] | None = None,
        reason: str = "",
        auto_approve_in_test: bool = False,
    ) -> ApprovalDecision: ...

    async def decide(
        self, request_id: str, *, approve: bool, decided_by: str = "user"
    ) -> ApprovalRequest: ...

    async def list_pending(self) -> list[ApprovalRequest]: ...


class DefaultApprovalEngine(BaseRepository):
    def __init__(self, db: Database, events: EventBus | None = None) -> None:
        super().__init__(db)
        self._events = events
        # In-process remember ask_once grants for this session
        self._session_grants: set[tuple[str, str, str]] = set()

    async def set_policy(
        self,
        resource_type: str,
        resource_id: str,
        level: ApprovalLevel | str,
        *,
        principal: str | None = None,
    ) -> ApprovalPolicy:
        lvl = level if isinstance(level, ApprovalLevel) else ApprovalLevel(level)
        now = utcnow_iso()
        policy = ApprovalPolicy(
            resource_type=resource_type,
            resource_id=resource_id,
            level=lvl,
            principal=principal,
            created_at=now,
            updated_at=now,
        )
        await self.db.execute(
            """
            INSERT INTO approval_policies
                (id, resource_type, resource_id, level, principal, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, '{}', ?, ?)
            ON CONFLICT(resource_type, resource_id, principal) DO UPDATE SET
                level = excluded.level,
                updated_at = excluded.updated_at
            """,
            (
                policy.id,
                policy.resource_type,
                policy.resource_id,
                policy.level.value,
                principal,
                now,
                now,
            ),
        )
        log.info(
            "approval.policy_set",
            type=resource_type,
            id=resource_id,
            level=lvl.value,
            principal=principal,
        )
        return policy

    async def get_level(
        self, resource_type: str, resource_id: str, *, principal: str | None = None
    ) -> ApprovalLevel:
        # Principal-specific then global
        for prin in (principal, None):
            row = await self.db.fetchone(
                """
                SELECT level FROM approval_policies
                WHERE resource_type = ? AND resource_id = ?
                  AND (principal IS ? OR (principal IS NULL AND ? IS NULL))
                """,
                (resource_type, resource_id, prin, prin),
            )
            if row:
                return ApprovalLevel(row["level"])
            # wildcard resource
            row = await self.db.fetchone(
                """
                SELECT level FROM approval_policies
                WHERE resource_type = ? AND resource_id = '*'
                  AND (principal IS ? OR (principal IS NULL AND ? IS NULL))
                """,
                (resource_type, prin, prin),
            )
            if row:
                return ApprovalLevel(row["level"])
        return _DEFAULT_LEVELS.get((resource_type, resource_id), ApprovalLevel.AUTOMATIC)

    async def check(
        self,
        resource_type: str,
        resource_id: str,
        action: str,
        *,
        principal: str = "user",
        payload: dict[str, Any] | None = None,
        reason: str = "",
        auto_approve_in_test: bool = False,
    ) -> ApprovalDecision:
        level = await self.get_level(resource_type, resource_id, principal=principal)

        if level == ApprovalLevel.DENY:
            req = await self._create_request(
                resource_type,
                resource_id,
                action,
                level,
                principal,
                reason or "denied by policy",
                payload,
                status=ApprovalStatus.DENIED,
            )
            return ApprovalDecision(
                allowed=False,
                status=ApprovalStatus.DENIED,
                request=req,
                message=f"Denied by policy: {resource_type}/{resource_id}",
            )

        if level == ApprovalLevel.AUTOMATIC:
            req = await self._create_request(
                resource_type,
                resource_id,
                action,
                level,
                principal,
                reason,
                payload,
                status=ApprovalStatus.AUTO_APPROVED,
            )
            return ApprovalDecision(
                allowed=True,
                status=ApprovalStatus.AUTO_APPROVED,
                request=req,
                message="auto-approved",
            )

        key = (resource_type, resource_id, principal)
        if level == ApprovalLevel.ASK_ONCE and key in self._session_grants:
            return ApprovalDecision(
                allowed=True,
                status=ApprovalStatus.APPROVED,
                message="session grant (ask_once)",
            )

        # ALWAYS_ASK or first ASK_ONCE
        if auto_approve_in_test:
            # Test/dev convenience — still audit
            req = await self._create_request(
                resource_type,
                resource_id,
                action,
                level,
                principal,
                reason or "auto_approve_in_test",
                payload,
                status=ApprovalStatus.APPROVED,
            )
            if level == ApprovalLevel.ASK_ONCE:
                self._session_grants.add(key)
            return ApprovalDecision(
                allowed=True,
                status=ApprovalStatus.APPROVED,
                request=req,
                message="approved (test mode)",
            )

        req = await self._create_request(
            resource_type,
            resource_id,
            action,
            level,
            principal,
            reason,
            payload,
            status=ApprovalStatus.PENDING,
        )
        if self._events:
            await self._events.publish(
                Event(
                    type="approval.requested",
                    payload={
                        "id": req.id,
                        "resource_type": resource_type,
                        "resource_id": resource_id,
                        "action": action,
                        "level": level.value,
                    },
                    source="approval",
                )
            )
        log.warning(
            "approval.pending",
            id=req.id,
            type=resource_type,
            resource=resource_id,
            action=action,
        )
        return ApprovalDecision(
            allowed=False,
            status=ApprovalStatus.PENDING,
            request=req,
            message=f"Approval required ({level.value}). Use approval.decide('{req.id}', approve=True).",
        )

    async def decide(
        self, request_id: str, *, approve: bool, decided_by: str = "user"
    ) -> ApprovalRequest:
        row = await self.db.fetchone(
            "SELECT * FROM approval_requests WHERE id = ?", (request_id,)
        )
        if row is None:
            raise KeyError(f"Approval request not found: {request_id}")
        status = ApprovalStatus.APPROVED if approve else ApprovalStatus.DENIED
        now = utcnow_iso()
        await self.db.execute(
            """
            UPDATE approval_requests
            SET status = ?, decided_by = ?, decided_at = ?
            WHERE id = ?
            """,
            (status.value, decided_by, now, request_id),
        )
        if approve:
            key = (row["resource_type"], row["resource_id"], row["principal"])
            if row["level"] == ApprovalLevel.ASK_ONCE.value:
                self._session_grants.add(key)
        if self._events:
            await self._events.publish(
                Event(
                    type="approval.decided",
                    payload={"id": request_id, "status": status.value, "by": decided_by},
                    source="approval",
                )
            )
        updated = await self.db.fetchone(
            "SELECT * FROM approval_requests WHERE id = ?", (request_id,)
        )
        return self._row_to_request(updated)

    async def list_pending(self) -> list[ApprovalRequest]:
        rows = await self.db.fetchall(
            "SELECT * FROM approval_requests WHERE status = 'pending' ORDER BY created_at DESC"
        )
        return [self._row_to_request(r) for r in rows]

    async def _create_request(
        self,
        resource_type: str,
        resource_id: str,
        action: str,
        level: ApprovalLevel,
        principal: str,
        reason: str,
        payload: dict[str, Any] | None,
        *,
        status: ApprovalStatus,
    ) -> ApprovalRequest:
        now = utcnow_iso()
        req = ApprovalRequest(
            id=new_id("areq"),
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            level=level,
            status=status,
            principal=principal,
            reason=reason or None,
            payload=payload or {},
            decided_by="system" if status != ApprovalStatus.PENDING else None,
            created_at=now,
            decided_at=now if status != ApprovalStatus.PENDING else None,
        )
        await self.db.execute(
            """
            INSERT INTO approval_requests
                (id, resource_type, resource_id, action, level, status, principal,
                 reason, payload, decided_by, created_at, decided_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                req.id,
                req.resource_type,
                req.resource_id,
                req.action,
                req.level.value,
                req.status.value,
                req.principal,
                req.reason,
                self.dumps(req.payload),
                req.decided_by,
                req.created_at,
                req.decided_at,
            ),
        )
        return req

    def _row_to_request(self, row: Any) -> ApprovalRequest:
        return ApprovalRequest(
            id=row["id"],
            resource_type=row["resource_type"],
            resource_id=row["resource_id"],
            action=row["action"],
            level=ApprovalLevel(row["level"]),
            status=ApprovalStatus(row["status"]),
            principal=row["principal"],
            reason=row["reason"],
            payload=self.loads(row["payload"], {}),
            decided_by=row["decided_by"],
            created_at=row["created_at"],
            decided_at=row["decided_at"],
        )

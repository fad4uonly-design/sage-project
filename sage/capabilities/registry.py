"""SQLite-backed capability registry."""

from __future__ import annotations

import re

from sage.capabilities.models import CapabilityDescriptor
from sage.db.connection import Database
from sage.db.repository import BaseRepository
from sage.logging import get_logger
from sage.utils.time import utcnow_iso

log = get_logger(__name__)


class SQLiteCapabilityRegistry(BaseRepository):
    def __init__(self, db: Database) -> None:
        super().__init__(db)

    async def register(self, descriptor: CapabilityDescriptor) -> CapabilityDescriptor:
        now = utcnow_iso()
        descriptor.updated_at = now
        existing = await self.get(descriptor.principal, descriptor.domain)
        if existing:
            descriptor.id = existing.id
            descriptor.created_at = existing.created_at
            await self.db.execute(
                """
                UPDATE capability_registry SET
                    principal_type = ?, capabilities = ?, tools = ?, permissions = ?,
                    reasoning_strategies = ?, confidence_threshold = ?, metadata = ?,
                    enabled = ?, updated_at = ?
                WHERE principal = ? AND domain = ?
                """,
                (
                    descriptor.principal_type,
                    self.dumps(descriptor.capabilities),
                    self.dumps(descriptor.tools),
                    self.dumps(descriptor.permissions),
                    self.dumps(descriptor.reasoning_strategies),
                    descriptor.confidence_threshold,
                    self.dumps(descriptor.metadata),
                    1 if descriptor.enabled else 0,
                    now,
                    descriptor.principal,
                    descriptor.domain,
                ),
            )
        else:
            descriptor.created_at = now
            await self.db.execute(
                """
                INSERT INTO capability_registry (
                    id, principal, principal_type, domain, capabilities, tools, permissions,
                    reasoning_strategies, confidence_threshold, metadata, enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    descriptor.id,
                    descriptor.principal,
                    descriptor.principal_type,
                    descriptor.domain,
                    self.dumps(descriptor.capabilities),
                    self.dumps(descriptor.tools),
                    self.dumps(descriptor.permissions),
                    self.dumps(descriptor.reasoning_strategies),
                    descriptor.confidence_threshold,
                    self.dumps(descriptor.metadata),
                    1 if descriptor.enabled else 0,
                    descriptor.created_at,
                    descriptor.updated_at,
                ),
            )
        log.info(
            "capabilities.registered",
            principal=descriptor.principal,
            domain=descriptor.domain,
        )
        return descriptor

    async def unregister(self, principal: str, domain: str) -> bool:
        cur = await self.db.execute(
            "DELETE FROM capability_registry WHERE principal = ? AND domain = ?",
            (principal, domain),
        )
        return (cur.rowcount or 0) > 0

    async def find_for_domain(self, domain: str) -> list[CapabilityDescriptor]:
        rows = await self.db.fetchall(
            """
            SELECT * FROM capability_registry
            WHERE enabled = 1 AND (domain = ? OR domain = 'general')
            ORDER BY domain = ? DESC
            """,
            (domain, domain),
        )
        return [self._row_to_desc(r) for r in rows]

    async def find_for_task(self, description: str) -> list[tuple[CapabilityDescriptor, float]]:
        all_caps = await self.list_all()
        lower = description.lower()
        tokens = set(re.findall(r"[a-z0-9_]+", lower))
        scored: list[tuple[CapabilityDescriptor, float]] = []
        for cap in all_caps:
            if not cap.enabled:
                continue
            score = 0.0
            if cap.domain != "general" and cap.domain in lower:
                score += 0.5
            for c in cap.capabilities:
                if c.lower() in lower or c.lower() in tokens:
                    score += 0.2
            for t in cap.tools:
                if t.lower() in lower:
                    score += 0.1
            # token overlap with domain
            if cap.domain in tokens:
                score += 0.3
            if score >= cap.confidence_threshold or (
                cap.domain == "general" and score >= 0.1
            ):
                scored.append((cap, min(1.0, score)))
            elif score > 0:
                scored.append((cap, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    async def list_all(self) -> list[CapabilityDescriptor]:
        rows = await self.db.fetchall(
            "SELECT * FROM capability_registry ORDER BY principal, domain"
        )
        return [self._row_to_desc(r) for r in rows]

    async def get(self, principal: str, domain: str) -> CapabilityDescriptor | None:
        row = await self.db.fetchone(
            "SELECT * FROM capability_registry WHERE principal = ? AND domain = ?",
            (principal, domain),
        )
        return self._row_to_desc(row) if row else None

    def _row_to_desc(self, row: object) -> CapabilityDescriptor:
        r = row
        return CapabilityDescriptor(
            id=r["id"],  # type: ignore[index]
            principal=r["principal"],  # type: ignore[index]
            principal_type=r["principal_type"],  # type: ignore[index]
            domain=r["domain"],  # type: ignore[index]
            capabilities=self.loads(r["capabilities"], []),  # type: ignore[index]
            tools=self.loads(r["tools"], []),  # type: ignore[index]
            permissions=self.loads(r["permissions"], []),  # type: ignore[index]
            reasoning_strategies=self.loads(r["reasoning_strategies"], []),  # type: ignore[index]
            confidence_threshold=float(r["confidence_threshold"]),  # type: ignore[index]
            metadata=self.loads(r["metadata"], {}),  # type: ignore[index]
            enabled=bool(r["enabled"]),  # type: ignore[index]
            created_at=r["created_at"],  # type: ignore[index]
            updated_at=r["updated_at"],  # type: ignore[index]
        )

"""Execution audit logger."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from sage.db.connection import Database
from sage.db.repository import BaseRepository
from sage.events.bus import EventBus
from sage.events.events import Event
from sage.logging import audit as file_audit
from sage.logging import get_logger
from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso

log = get_logger(__name__)


class AuditRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("aud"))
    kind: str  # workflow | skill | tool | agent | approval | system
    subject_id: str | None = None
    workflow_run_id: str | None = None
    skill_id: str | None = None
    tool_name: str | None = None
    agent_id: str | None = None
    principal: str | None = None
    status: str = "ok"
    summary: str | None = None
    reasoning: str | None = None
    confidence: float | None = None
    duration_ms: float | None = None
    approvals: list[str] = Field(default_factory=list)
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utcnow_iso)


@runtime_checkable
class ExecutionAudit(Protocol):
    async def record(self, **fields: Any) -> AuditRecord: ...

    async def list_recent(self, *, limit: int = 50, kind: str | None = None) -> list[AuditRecord]: ...

    async def for_run(self, workflow_run_id: str) -> list[AuditRecord]: ...


class AuditLogger(BaseRepository):
    def __init__(self, db: Database, events: EventBus | None = None) -> None:
        super().__init__(db)
        self._events = events

    async def record(
        self,
        *,
        kind: str,
        status: str = "ok",
        subject_id: str | None = None,
        workflow_run_id: str | None = None,
        skill_id: str | None = None,
        tool_name: str | None = None,
        agent_id: str | None = None,
        principal: str | None = None,
        summary: str | None = None,
        reasoning: str | None = None,
        confidence: float | None = None,
        duration_ms: float | None = None,
        approvals: list[str] | None = None,
        detail: dict[str, Any] | None = None,
    ) -> AuditRecord:
        rec = AuditRecord(
            kind=kind,
            status=status,
            subject_id=subject_id,
            workflow_run_id=workflow_run_id,
            skill_id=skill_id,
            tool_name=tool_name,
            agent_id=agent_id,
            principal=principal,
            summary=summary,
            reasoning=reasoning,
            confidence=confidence,
            duration_ms=duration_ms,
            approvals=list(approvals or []),
            detail=dict(detail or {}),
        )
        await self.db.execute(
            """
            INSERT INTO execution_audit (
                id, kind, subject_id, workflow_run_id, skill_id, tool_name, agent_id,
                principal, status, summary, reasoning, confidence, duration_ms,
                approvals, detail, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rec.id,
                rec.kind,
                rec.subject_id,
                rec.workflow_run_id,
                rec.skill_id,
                rec.tool_name,
                rec.agent_id,
                rec.principal,
                rec.status,
                rec.summary,
                rec.reasoning,
                rec.confidence,
                rec.duration_ms,
                self.dumps(rec.approvals),
                self.dumps(rec.detail),
                rec.created_at,
            ),
        )
        # Mirror to structured audit log file
        try:
            file_audit(
                "execution",
                kind=kind,
                status=status,
                summary=summary,
                skill_id=skill_id,
                tool_name=tool_name,
                workflow_run_id=workflow_run_id,
            )
        except Exception:
            pass
        if self._events:
            await self._events.publish(
                Event(
                    type="audit.recorded",
                    payload={"id": rec.id, "kind": kind, "status": status},
                    source="audit",
                )
            )
        log.debug("audit.recorded", id=rec.id, kind=kind, status=status)
        return rec

    async def list_recent(self, *, limit: int = 50, kind: str | None = None) -> list[AuditRecord]:
        if kind:
            rows = await self.db.fetchall(
                """
                SELECT * FROM execution_audit WHERE kind = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (kind, limit),
            )
        else:
            rows = await self.db.fetchall(
                "SELECT * FROM execution_audit ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        return [self._row_to_rec(r) for r in rows]

    async def for_run(self, workflow_run_id: str) -> list[AuditRecord]:
        rows = await self.db.fetchall(
            """
            SELECT * FROM execution_audit
            WHERE workflow_run_id = ?
            ORDER BY created_at ASC
            """,
            (workflow_run_id,),
        )
        return [self._row_to_rec(r) for r in rows]

    def _row_to_rec(self, row: Any) -> AuditRecord:
        return AuditRecord(
            id=row["id"],
            kind=row["kind"],
            subject_id=row["subject_id"],
            workflow_run_id=row["workflow_run_id"],
            skill_id=row["skill_id"],
            tool_name=row["tool_name"],
            agent_id=row["agent_id"],
            principal=row["principal"],
            status=row["status"],
            summary=row["summary"],
            reasoning=row["reasoning"],
            confidence=row["confidence"],
            duration_ms=row["duration_ms"],
            approvals=self.loads(row["approvals"], []),
            detail=self.loads(row["detail"], {}),
            created_at=row["created_at"],
        )

"""Automation Manager implementation."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from sage.db.connection import Database
from sage.db.repository import BaseRepository
from sage.events.bus import EventBus
from sage.events.events import Event, KnowledgeEvents
from sage.logging import get_logger
from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso

log = get_logger(__name__)


class AutomationJob(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ajob"))
    name: str
    trigger_type: str  # cron | interval | event | manual
    trigger_config: dict[str, Any] = Field(default_factory=dict)
    workflow_id: str | None = None
    skill_id: str | None = None
    enabled: bool = True
    last_run_at: str | None = None
    last_status: str | None = None
    run_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utcnow_iso)
    updated_at: str = Field(default_factory=utcnow_iso)


@runtime_checkable
class AutomationManager(Protocol):
    async def register_job(self, job: AutomationJob) -> AutomationJob: ...

    async def list_jobs(self) -> list[AutomationJob]: ...

    async def enable(self, name: str, enabled: bool = True) -> bool: ...

    async def run_job(self, name: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]: ...

    async def handle_event(self, event: Event) -> list[dict[str, Any]]: ...


class DefaultAutomationManager(BaseRepository):
    def __init__(self, db: Database, container: Any, events: EventBus | None = None) -> None:
        super().__init__(db)
        self._container = container
        self._events = events
        self._subs: list[Any] = []

    async def register_job(self, job: AutomationJob) -> AutomationJob:
        now = utcnow_iso()
        job.updated_at = now
        await self.db.execute(
            """
            INSERT INTO automation_jobs (
                id, name, trigger_type, trigger_config, workflow_id, skill_id,
                enabled, last_run_at, last_status, run_count, metadata, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                trigger_type = excluded.trigger_type,
                trigger_config = excluded.trigger_config,
                workflow_id = excluded.workflow_id,
                skill_id = excluded.skill_id,
                enabled = excluded.enabled,
                metadata = excluded.metadata,
                updated_at = excluded.updated_at
            """,
            (
                job.id,
                job.name,
                job.trigger_type,
                self.dumps(job.trigger_config),
                job.workflow_id,
                job.skill_id,
                1 if job.enabled else 0,
                job.last_run_at,
                job.last_status,
                job.run_count,
                self.dumps(job.metadata),
                job.created_at,
                job.updated_at,
            ),
        )
        log.info("automation.job_registered", name=job.name, trigger=job.trigger_type)
        return job

    async def list_jobs(self) -> list[AutomationJob]:
        rows = await self.db.fetchall("SELECT * FROM automation_jobs ORDER BY name")
        return [self._row_to_job(r) for r in rows]

    async def enable(self, name: str, enabled: bool = True) -> bool:
        cur = await self.db.execute(
            "UPDATE automation_jobs SET enabled = ?, updated_at = ? WHERE name = ?",
            (1 if enabled else 0, utcnow_iso(), name),
        )
        return (cur.rowcount or 0) > 0

    async def run_job(
        self, name: str, *, context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        row = await self.db.fetchone("SELECT * FROM automation_jobs WHERE name = ?", (name,))
        if row is None:
            raise KeyError(f"Unknown automation job: {name}")
        job = self._row_to_job(row)
        if not job.enabled:
            return {"success": False, "error": "job disabled", "name": name}

        ctx = dict(context or {})
        ctx.setdefault("task", job.metadata.get("task") or job.name)
        result: dict[str, Any] = {"name": name, "success": False}

        try:
            if job.workflow_id:
                from sage.workflow.engine import WorkflowEngine

                engine = self._container.try_resolve(WorkflowEngine)
                if not engine:
                    raise RuntimeError("WorkflowEngine unavailable")
                # resolve by id or name
                run = await engine.start(job.workflow_id, context=ctx, principal="automation")
                result = {
                    "name": name,
                    "success": run.status.value == "succeeded",
                    "workflow_run_id": run.id,
                    "status": run.status.value,
                    "error": run.error,
                    "result": run.result,
                }
            elif job.skill_id:
                from sage.skills.interfaces import SkillLibrary

                lib = self._container.try_resolve(SkillLibrary)
                if not lib:
                    raise RuntimeError("SkillLibrary unavailable")
                sk = await lib.invoke(
                    job.skill_id,
                    task=str(ctx.get("task") or job.name),
                    context=ctx,
                    principal="automation",
                )
                result = {
                    "name": name,
                    "success": sk.success,
                    "skill_id": job.skill_id,
                    "output": sk.output,
                    "error": sk.error,
                }
            else:
                result = {"name": name, "success": False, "error": "No workflow_id or skill_id"}
        except Exception as exc:
            log.exception("automation.job_failed", name=name)
            result = {"name": name, "success": False, "error": str(exc)}

        await self.db.execute(
            """
            UPDATE automation_jobs
            SET last_run_at = ?, last_status = ?, run_count = run_count + 1, updated_at = ?
            WHERE name = ?
            """,
            (
                utcnow_iso(),
                "ok" if result.get("success") else "error",
                utcnow_iso(),
                name,
            ),
        )

        # Audit
        from sage.audit.logger import ExecutionAudit

        audit = self._container.try_resolve(ExecutionAudit)
        if audit:
            await audit.record(
                kind="automation",
                subject_id=name,
                status="ok" if result.get("success") else "error",
                summary=f"Automation job {name}",
                workflow_run_id=result.get("workflow_run_id"),
                skill_id=result.get("skill_id"),
                principal="automation",
                detail=result,
            )
        return result

    async def handle_event(self, event: Event) -> list[dict[str, Any]]:
        jobs = await self.list_jobs()
        results = []
        for job in jobs:
            if not job.enabled or job.trigger_type != "event":
                continue
            event_type = str(job.trigger_config.get("event_type") or "")
            if not event_type or event_type == event.type or (
                event_type.endswith(".*")
                and event.type.startswith(event_type[:-2])
            ):
                ctx = {
                    "task": job.metadata.get("task") or f"Event {event.type}",
                    "event_type": event.type,
                    "event_payload": event.payload,
                    **{k: v for k, v in event.payload.items() if isinstance(k, str)},
                }
                # map common fields
                if "path" in event.payload:
                    ctx["path"] = event.payload["path"]
                results.append(await self.run_job(job.name, context=ctx))
        return results

    async def bind_event_triggers(self) -> None:
        if not self._events:
            return

        async def _on_any(event: Event) -> None:
            # Only process event-triggered jobs; cheap filter
            try:
                await self.handle_event(event)
            except Exception:
                log.exception("automation.event_handler_failed", type=event.type)

        # Subscribe to document ingest and file index broadly
        self._subs = [
            self._events.subscribe(KnowledgeEvents.INGESTED, _on_any),
            self._events.subscribe("files.indexed", _on_any),
            self._events.subscribe("automation.tick", _on_any),
        ]

    async def unbind(self) -> None:
        if self._events:
            for s in self._subs:
                self._events.unsubscribe(s)
        self._subs.clear()

    def _row_to_job(self, row: Any) -> AutomationJob:
        return AutomationJob(
            id=row["id"],
            name=row["name"],
            trigger_type=row["trigger_type"],
            trigger_config=self.loads(row["trigger_config"], {}),
            workflow_id=row["workflow_id"],
            skill_id=row["skill_id"],
            enabled=bool(row["enabled"]),
            last_run_at=row["last_run_at"],
            last_status=row["last_status"],
            run_count=int(row["run_count"] or 0),
            metadata=self.loads(row["metadata"], {}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

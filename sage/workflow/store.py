"""Persistence for workflow definitions and runs."""

from __future__ import annotations

from typing import Any

from sage.db.connection import Database
from sage.db.repository import BaseRepository
from sage.utils.time import utcnow_iso
from sage.workflow.models import (
    StepRunRecord,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowStatus,
    WorkflowStepDef,
)


class WorkflowStore(BaseRepository):
    def __init__(self, db: Database) -> None:
        super().__init__(db)

    async def save_definition(self, definition: WorkflowDefinition) -> None:
        now = utcnow_iso()
        await self.db.execute(
            """
            INSERT INTO workflow_definitions
                (id, name, version, description, definition, tags, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                version = excluded.version,
                description = excluded.description,
                definition = excluded.definition,
                tags = excluded.tags,
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (
                definition.id,
                definition.name,
                definition.version,
                definition.description,
                self.dumps(definition.model_dump(mode="json")),
                self.dumps(definition.tags),
                1 if definition.enabled else 0,
                now,
                now,
            ),
        )

    async def load_definition(self, definition_id: str) -> WorkflowDefinition | None:
        row = await self.db.fetchone(
            "SELECT * FROM workflow_definitions WHERE id = ? OR name = ?",
            (definition_id, definition_id),
        )
        if row is None:
            return None
        data = self.loads(row["definition"], {})
        return WorkflowDefinition.model_validate(data)

    async def list_definitions(self) -> list[WorkflowDefinition]:
        rows = await self.db.fetchall(
            "SELECT definition FROM workflow_definitions WHERE enabled = 1 ORDER BY name"
        )
        out: list[WorkflowDefinition] = []
        for r in rows:
            try:
                out.append(WorkflowDefinition.model_validate(self.loads(r["definition"], {})))
            except Exception:
                continue
        return out

    async def save_run(self, run: WorkflowRun) -> None:
        await self.db.execute(
            """
            INSERT INTO workflow_runs (
                id, definition_id, status, context, current_step, checkpoint,
                result, error, started_at, updated_at, completed_at, principal, parent_run_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status = excluded.status,
                context = excluded.context,
                current_step = excluded.current_step,
                checkpoint = excluded.checkpoint,
                result = excluded.result,
                error = excluded.error,
                updated_at = excluded.updated_at,
                completed_at = excluded.completed_at
            """,
            (
                run.id,
                run.definition_id,
                run.status.value,
                self.dumps(run.context),
                run.current_step,
                self.dumps(run.checkpoint),
                self.dumps(run.result) if run.result is not None else None,
                run.error,
                run.started_at,
                run.updated_at,
                run.completed_at,
                run.principal,
                run.parent_run_id,
            ),
        )

    async def load_run(self, run_id: str) -> WorkflowRun | None:
        row = await self.db.fetchone("SELECT * FROM workflow_runs WHERE id = ?", (run_id,))
        if row is None:
            return None
        steps = await self.db.fetchall(
            "SELECT * FROM workflow_step_runs WHERE run_id = ? ORDER BY started_at ASC",
            (run_id,),
        )
        history = [
            StepRunRecord(
                id=s["id"],
                step_id=s["step_id"],
                status=s["status"],
                attempt=s["attempt"],
                input=self.loads(s["input"], {}),
                output=self.loads(s["output"]) if s["output"] else None,
                error=s["error"],
                started_at=s["started_at"],
                completed_at=s["completed_at"],
            )
            for s in steps
        ]
        # Also try to recover definition name
        defn = await self.load_definition(row["definition_id"])
        return WorkflowRun(
            id=row["id"],
            definition_id=row["definition_id"],
            definition_name=defn.name if defn else "",
            status=WorkflowStatus(row["status"]),
            context=self.loads(row["context"], {}),
            current_step=row["current_step"],
            checkpoint=self.loads(row["checkpoint"], {}),
            step_history=history,
            result=self.loads(row["result"]) if row["result"] else None,
            error=row["error"],
            started_at=row["started_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            principal=row["principal"],
            parent_run_id=row["parent_run_id"],
        )

    async def save_step(self, run_id: str, record: StepRunRecord) -> None:
        await self.db.execute(
            """
            INSERT INTO workflow_step_runs (
                id, run_id, step_id, status, attempt, input, output, error, started_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status = excluded.status,
                attempt = excluded.attempt,
                output = excluded.output,
                error = excluded.error,
                completed_at = excluded.completed_at
            """,
            (
                record.id,
                run_id,
                record.step_id,
                record.status,
                record.attempt,
                self.dumps(record.input),
                self.dumps(record.output) if record.output is not None else None,
                record.error,
                record.started_at,
                record.completed_at,
            ),
        )

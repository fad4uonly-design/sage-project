"""Goal Engine implementation."""

from __future__ import annotations

import builtins
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from sage.db.connection import Database
from sage.db.repository import BaseRepository
from sage.logging import get_logger
from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso

log = get_logger(__name__)


class GoalHorizon(StrEnum):
    LONG = "long"
    MEDIUM = "medium"
    DAILY = "daily"


class GoalStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    PAUSED = "paused"
    BLOCKED = "blocked"


class RichGoal(BaseModel):
    id: str = Field(default_factory=lambda: new_id("cgoal"))
    title: str
    description: str = ""
    horizon: GoalHorizon = GoalHorizon.MEDIUM
    status: GoalStatus = GoalStatus.ACTIVE
    priority: float = Field(default=0.5, ge=0.0, le=1.0)
    parent_id: str | None = None
    project_id: str | None = None
    success_metrics: list[str] = Field(default_factory=list)
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    due_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utcnow_iso)
    updated_at: str = Field(default_factory=utcnow_iso)
    completed_at: str | None = None


@runtime_checkable
class GoalEngine(Protocol):
    async def create(self, title: str, **kwargs: Any) -> RichGoal: ...

    async def get(self, goal_id: str) -> RichGoal | None: ...

    async def update(self, goal_id: str, **fields: Any) -> RichGoal: ...

    async def list(
        self,
        *,
        status: GoalStatus | str | None = "active",
        horizon: GoalHorizon | str | None = None,
        project_id: str | None = None,
        limit: int = 50,
    ) -> builtins.list[RichGoal]: ...

    async def complete(self, goal_id: str, *, progress: float = 1.0) -> RichGoal: ...

    async def children(self, parent_id: str) -> builtins.list[RichGoal]: ...

    async def tree(self, root_id: str) -> dict[str, Any]: ...


class SQLiteGoalEngine(BaseRepository):
    def __init__(self, db: Database) -> None:
        super().__init__(db)

    async def create(self, title: str, **kwargs: Any) -> RichGoal:
        horizon = kwargs.get("horizon", GoalHorizon.MEDIUM)
        if not isinstance(horizon, GoalHorizon):
            horizon = GoalHorizon(horizon)
        goal = RichGoal(
            title=title,
            description=str(kwargs.get("description") or ""),
            horizon=horizon,
            priority=float(kwargs.get("priority", 0.5)),
            parent_id=kwargs.get("parent_id"),
            project_id=kwargs.get("project_id"),
            success_metrics=list(kwargs.get("success_metrics") or []),
            due_at=kwargs.get("due_at"),
            metadata=dict(kwargs.get("metadata") or {}),
        )
        await self.db.execute(
            """
            INSERT INTO context_goals (
                id, title, description, horizon, status, priority, parent_id, project_id,
                success_metrics, progress, due_at, metadata, created_at, updated_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                goal.id,
                goal.title,
                goal.description,
                goal.horizon.value,
                goal.status.value,
                goal.priority,
                goal.parent_id,
                goal.project_id,
                self.dumps(goal.success_metrics),
                goal.progress,
                goal.due_at,
                self.dumps(goal.metadata),
                goal.created_at,
                goal.updated_at,
            ),
        )
        log.info("goals.created", id=goal.id, title=goal.title, horizon=goal.horizon.value)
        return goal

    async def get(self, goal_id: str) -> RichGoal | None:
        row = await self.db.fetchone("SELECT * FROM context_goals WHERE id = ?", (goal_id,))
        return self._row_to_goal(row) if row else None

    async def update(self, goal_id: str, **fields: Any) -> RichGoal:
        goal = await self.get(goal_id)
        if goal is None:
            raise KeyError(goal_id)
        data = goal.model_dump()
        for k, v in fields.items():
            if k in data and k not in {"id", "created_at"}:
                if k == "horizon" and not isinstance(v, GoalHorizon):
                    v = GoalHorizon(v)
                if k == "status" and not isinstance(v, GoalStatus):
                    v = GoalStatus(v)
                data[k] = v
        data["updated_at"] = utcnow_iso()
        updated = RichGoal.model_validate(data)
        await self.db.execute(
            """
            UPDATE context_goals SET
                title=?, description=?, horizon=?, status=?, priority=?,
                parent_id=?, project_id=?, success_metrics=?, progress=?,
                due_at=?, metadata=?, updated_at=?, completed_at=?
            WHERE id=?
            """,
            (
                updated.title,
                updated.description,
                updated.horizon.value
                if isinstance(updated.horizon, GoalHorizon)
                else updated.horizon,
                updated.status.value
                if isinstance(updated.status, GoalStatus)
                else updated.status,
                updated.priority,
                updated.parent_id,
                updated.project_id,
                self.dumps(updated.success_metrics),
                updated.progress,
                updated.due_at,
                self.dumps(updated.metadata),
                updated.updated_at,
                updated.completed_at,
                updated.id,
            ),
        )
        return updated

    async def list(
        self,
        *,
        status: GoalStatus | str | None = "active",
        horizon: GoalHorizon | str | None = None,
        project_id: str | None = None,
        limit: int = 50,
    ) -> builtins.list[RichGoal]:
        clauses: builtins.list[str] = []
        params: builtins.list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value if isinstance(status, GoalStatus) else status)
        if horizon is not None:
            clauses.append("horizon = ?")
            params.append(horizon.value if isinstance(horizon, GoalHorizon) else horizon)
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = await self.db.fetchall(
            f"""
            SELECT * FROM context_goals {where}
            ORDER BY priority DESC, updated_at DESC LIMIT ?
            """,
            tuple(params),
        )
        return [self._row_to_goal(r) for r in rows]

    async def complete(self, goal_id: str, *, progress: float = 1.0) -> RichGoal:
        now = utcnow_iso()
        return await self.update(
            goal_id,
            status=GoalStatus.COMPLETED,
            progress=min(1.0, max(0.0, progress)),
            completed_at=now,
        )

    async def children(self, parent_id: str) -> builtins.list[RichGoal]:
        rows = await self.db.fetchall(
            """
            SELECT * FROM context_goals WHERE parent_id = ?
            ORDER BY priority DESC
            """,
            (parent_id,),
        )
        return [self._row_to_goal(r) for r in rows]

    async def tree(self, root_id: str) -> dict[str, Any]:
        root = await self.get(root_id)
        if root is None:
            raise KeyError(root_id)

        async def build(gid: str) -> dict[str, Any]:
            g = await self.get(gid)
            assert g is not None
            kids = await self.children(gid)
            return {
                "goal": g.model_dump(),
                "children": [await build(c.id) for c in kids],
            }

        return await build(root_id)

    def _row_to_goal(self, row: Any) -> RichGoal:
        return RichGoal(
            id=row["id"],
            title=row["title"],
            description=row["description"] or "",
            horizon=GoalHorizon(row["horizon"]),
            status=GoalStatus(row["status"]),
            priority=float(row["priority"]),
            parent_id=row["parent_id"],
            project_id=row["project_id"],
            success_metrics=self.loads(row["success_metrics"], []),
            progress=float(row["progress"] or 0),
            due_at=row["due_at"],
            metadata=self.loads(row["metadata"], {}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
        )

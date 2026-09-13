"""Project manager persistence and API."""

from __future__ import annotations

import builtins
from typing import Any, Protocol, runtime_checkable

from sage.db.connection import Database
from sage.db.repository import BaseRepository
from sage.logging import get_logger
from sage.projects.models import Project, ProjectLink, ProjectLinkType, ProjectStatus
from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso

log = get_logger(__name__)


@runtime_checkable
class ProjectManager(Protocol):
    async def create(self, name: str, **kwargs: Any) -> Project: ...

    async def get(self, project_id: str) -> Project | None: ...

    async def update(self, project_id: str, **fields: Any) -> Project: ...

    async def list(
        self, *, status: ProjectStatus | str | None = None, limit: int = 50
    ) -> builtins.list[Project]: ...

    async def touch(self, project_id: str) -> None: ...

    async def link(
        self,
        project_id: str,
        link_type: ProjectLinkType | str,
        link_ref: str,
        *,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProjectLink: ...

    async def links(
        self, project_id: str, *, link_type: str | None = None
    ) -> builtins.list[ProjectLink]: ...

    async def search(self, query: str, *, limit: int = 20) -> builtins.list[Project]: ...


class SQLiteProjectManager(BaseRepository):
    def __init__(self, db: Database) -> None:
        super().__init__(db)

    async def create(self, name: str, **kwargs: Any) -> Project:
        project = Project(
            name=name,
            description=str(kwargs.get("description") or ""),
            status=ProjectStatus(kwargs["status"])
            if kwargs.get("status")
            else ProjectStatus.ACTIVE,
            priority=float(kwargs.get("priority", 0.5)),
            domain=kwargs.get("domain"),
            objectives=list(kwargs.get("objectives") or []),
            tags=list(kwargs.get("tags") or []),
            metadata=dict(kwargs.get("metadata") or {}),
            progress=float(kwargs.get("progress", 0.0)),
        )
        await self.db.execute(
            """
            INSERT INTO projects (
                id, name, description, status, priority, domain, objectives, tags,
                metadata, progress, created_at, updated_at, completed_at, last_accessed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                project.id,
                project.name,
                project.description,
                project.status.value,
                project.priority,
                project.domain,
                self.dumps(project.objectives),
                self.dumps(project.tags),
                self.dumps(project.metadata),
                project.progress,
                project.created_at,
                project.updated_at,
                project.created_at,
            ),
        )
        log.info("projects.created", id=project.id, name=project.name)
        return project

    async def get(self, project_id: str) -> Project | None:
        row = await self.db.fetchone("SELECT * FROM projects WHERE id = ?", (project_id,))
        return self._row_to_project(row) if row else None

    async def update(self, project_id: str, **fields: Any) -> Project:
        project = await self.get(project_id)
        if project is None:
            raise KeyError(project_id)
        data = project.model_dump()
        for k, v in fields.items():
            if k in data and k not in {"id", "created_at"}:
                if k == "status" and not isinstance(v, ProjectStatus):
                    v = ProjectStatus(v)
                data[k] = v
        data["updated_at"] = utcnow_iso()
        if data.get("status") == ProjectStatus.COMPLETED and not data.get("completed_at"):
            data["completed_at"] = data["updated_at"]
        updated = Project.model_validate(data)
        await self.db.execute(
            """
            UPDATE projects SET
                name=?, description=?, status=?, priority=?, domain=?,
                objectives=?, tags=?, metadata=?, progress=?,
                updated_at=?, completed_at=?, last_accessed_at=?
            WHERE id=?
            """,
            (
                updated.name,
                updated.description,
                updated.status.value
                if isinstance(updated.status, ProjectStatus)
                else updated.status,
                updated.priority,
                updated.domain,
                self.dumps(updated.objectives),
                self.dumps(updated.tags),
                self.dumps(updated.metadata),
                updated.progress,
                updated.updated_at,
                updated.completed_at,
                updated.last_accessed_at,
                updated.id,
            ),
        )
        return updated

    async def list(
        self, *, status: ProjectStatus | str | None = None, limit: int = 50
    ) -> builtins.list[Project]:
        if status is not None:
            st = status.value if isinstance(status, ProjectStatus) else status
            rows = await self.db.fetchall(
                """
                SELECT * FROM projects WHERE status = ?
                ORDER BY priority DESC, updated_at DESC LIMIT ?
                """,
                (st, limit),
            )
        else:
            rows = await self.db.fetchall(
                """
                SELECT * FROM projects
                ORDER BY priority DESC, updated_at DESC LIMIT ?
                """,
                (limit,),
            )
        return [self._row_to_project(r) for r in rows]

    async def touch(self, project_id: str) -> None:
        now = utcnow_iso()
        await self.db.execute(
            "UPDATE projects SET last_accessed_at = ?, updated_at = ? WHERE id = ?",
            (now, now, project_id),
        )

    async def link(
        self,
        project_id: str,
        link_type: ProjectLinkType | str,
        link_ref: str,
        *,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProjectLink:
        if await self.get(project_id) is None:
            raise KeyError(project_id)
        lt = link_type.value if isinstance(link_type, ProjectLinkType) else str(link_type)
        link = ProjectLink(
            id=new_id("plink"),
            project_id=project_id,
            link_type=lt,
            link_ref=link_ref,
            title=title,
            metadata=dict(metadata or {}),
        )
        await self.db.execute(
            """
            INSERT INTO project_links
                (id, project_id, link_type, link_ref, title, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                link.id,
                link.project_id,
                lt,
                link.link_ref,
                link.title,
                self.dumps(link.metadata),
                link.created_at,
            ),
        )
        await self.touch(project_id)
        return link

    async def links(
        self, project_id: str, *, link_type: str | None = None
    ) -> builtins.list[ProjectLink]:
        if link_type:
            rows = await self.db.fetchall(
                """
                SELECT * FROM project_links
                WHERE project_id = ? AND link_type = ?
                ORDER BY created_at DESC
                """,
                (project_id, link_type),
            )
        else:
            rows = await self.db.fetchall(
                """
                SELECT * FROM project_links
                WHERE project_id = ?
                ORDER BY created_at DESC
                """,
                (project_id,),
            )
        return [
            ProjectLink(
                id=r["id"],
                project_id=r["project_id"],
                link_type=r["link_type"],
                link_ref=r["link_ref"],
                title=r["title"],
                metadata=self.loads(r["metadata"], {}),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    async def search(self, query: str, *, limit: int = 20) -> builtins.list[Project]:
        q = f"%{query.strip()}%"
        rows = await self.db.fetchall(
            """
            SELECT * FROM projects
            WHERE name LIKE ? OR IFNULL(description,'') LIKE ? OR tags LIKE ?
            ORDER BY priority DESC LIMIT ?
            """,
            (q, q, q, limit),
        )
        return [self._row_to_project(r) for r in rows]

    def _row_to_project(self, row: Any) -> Project:
        return Project(
            id=row["id"],
            name=row["name"],
            description=row["description"] or "",
            status=ProjectStatus(row["status"]),
            priority=float(row["priority"]),
            domain=row["domain"],
            objectives=self.loads(row["objectives"], []),
            tags=self.loads(row["tags"], []),
            metadata=self.loads(row["metadata"], {}),
            progress=float(row["progress"] or 0),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            last_accessed_at=row["last_accessed_at"],
        )

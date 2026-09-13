"""
Cognitive Context Engine.

Fuses memory, knowledge graph, projects, goals, automation, and approvals
into a unified situational model for the Orchestrator.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from sage.context.models import (
    ContextSnapshot,
    ProactiveSuggestion,
    SessionContinuity,
    UnifiedContext,
)
from sage.db.connection import Database
from sage.db.repository import BaseRepository
from sage.logging import get_logger
from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso

log = get_logger(__name__)


@runtime_checkable
class CognitiveContextEngine(Protocol):
    async def fuse(self) -> UnifiedContext: ...

    async def continuity(self) -> SessionContinuity: ...

    async def set_active_project(self, project_id: str | None) -> None: ...

    async def get_active_project_id(self) -> str | None: ...

    async def record_interest(self, topic: str, *, weight: float = 0.1) -> None: ...

    async def suggestions(self, *, limit: int = 10) -> list[ProactiveSuggestion]: ...

    async def generate_suggestions(self) -> list[ProactiveSuggestion]: ...

    async def dismiss_suggestion(self, suggestion_id: str) -> bool: ...

    async def snapshot(self, *, kind: str = "session") -> ContextSnapshot: ...

    async def bootstrap_session(self) -> UnifiedContext: ...


class DefaultCognitiveContextEngine(BaseRepository):
    def __init__(self, db: Database, container: Any) -> None:
        super().__init__(db)
        self._container = container
        self._cached: UnifiedContext | None = None

    async def fuse(self) -> UnifiedContext:
        ctx = UnifiedContext(environment=self._environment())

        # Projects
        from sage.projects.manager import ProjectManager

        pm = self._container.try_resolve(ProjectManager)
        if pm:
            projects = await pm.list(status="active", limit=20)
            ctx.active_projects = [p.model_dump() for p in projects]
            active_id = await self.get_active_project_id()
            if active_id:
                # pin active project first
                ctx.active_projects.sort(
                    key=lambda p: (0 if p.get("id") == active_id else 1, -float(p.get("priority") or 0))
                )

        # Goals
        from sage.goals.engine import GoalEngine

        ge = self._container.try_resolve(GoalEngine)
        if ge:
            goals = await ge.list(status="active", limit=30)
            ctx.goals = [g.model_dump() for g in goals]
            # derive open tasks from daily goals
            daily = [g for g in goals if g.horizon.value == "daily"]
            ctx.open_tasks = [
                {
                    "id": g.id,
                    "title": g.title,
                    "progress": g.progress,
                    "due_at": g.due_at,
                    "project_id": g.project_id,
                }
                for g in daily
            ]
            ctx.priorities = [
                g.title
                for g in sorted(goals, key=lambda x: x.priority, reverse=True)[:8]
            ]

        # Memory
        from sage.memory.interfaces import MemorySystem

        mem = self._container.try_resolve(MemorySystem)
        if mem:
            items = await mem.recall("", limit=8)
            ctx.recent_memories = [m.content for m in items]

        # Knowledge graph highlights from interests + project names
        from sage.knowledge.graph.interfaces import KnowledgeGraph

        kg = self._container.try_resolve(KnowledgeGraph)
        if kg:
            seeds = list(ctx.priorities[:3]) + [
                p.get("name", "") for p in ctx.active_projects[:3]
            ]
            facts: list[str] = []
            for seed in seeds:
                if not seed:
                    continue
                ents = await kg.search_entities(str(seed), limit=2)
                for ent in ents:
                    for t in await kg.neighbors(ent.id, direction="both", limit=2):
                        facts.append(f"{t.subject.name} —{t.relation}→ {t.object.name}")
            # de-dupe
            seen: set[str] = set()
            for f in facts:
                if f not in seen:
                    seen.add(f)
                    ctx.graph_highlights.append(f)
                if len(ctx.graph_highlights) >= 10:
                    break

        # Workflows unfinished
        try:
            # Query runs directly for unfinished
            rows = await self.db.fetchall(
                """
                SELECT id, definition_id, status, current_step, started_at
                FROM workflow_runs
                WHERE status IN ('running', 'waiting_approval', 'paused', 'pending')
                ORDER BY updated_at DESC LIMIT 10
                """
            )
            ctx.running_workflows = [
                {
                    "id": r["id"],
                    "definition_id": r["definition_id"],
                    "status": r["status"],
                    "current_step": r["current_step"],
                    "started_at": r["started_at"],
                }
                for r in rows
            ]
        except Exception:
            pass

        # Pending approvals
        from sage.approval.engine import ApprovalEngine

        appr = self._container.try_resolve(ApprovalEngine)
        if appr:
            pending = await appr.list_pending()
            ctx.pending_approvals = [
                {
                    "id": p.id,
                    "resource_type": p.resource_type,
                    "resource_id": p.resource_id,
                    "action": p.action,
                    "created_at": p.created_at,
                }
                for p in pending[:20]
            ]

        # Recent documents from knowledge
        try:
            rows = await self.db.fetchall(
                """
                SELECT id, title, path, category FROM knowledge_documents
                WHERE deleted_at IS NULL
                ORDER BY ingested_at DESC LIMIT 5
                """
            )
            ctx.recent_documents = [
                r["title"] or r["path"] or r["id"] for r in rows
            ]
        except Exception:
            pass

        # Long-term interests from learning patterns + stored state
        ctx.long_term_interests = await self._load_interests()

        # Suggestions
        sugg = await self.suggestions(limit=8)
        ctx.suggestions = [s.model_dump() for s in sugg]

        # Session continuity bundle
        ctx.session = await self.continuity()
        ctx.session.pending_approvals = ctx.pending_approvals
        ctx.session.unfinished_workflows = ctx.running_workflows
        ctx.session.active_goal_ids = [g["id"] for g in ctx.goals[:10] if g.get("id")]
        ctx.session.priorities = list(ctx.priorities)

        ctx.summary = self._summarize(ctx)
        self._cached = ctx
        return ctx

    async def continuity(self) -> SessionContinuity:
        active = await self.get_active_project_id()
        last_summary = await self._get_state("last_conversation_summary")
        interests = await self._load_interests()
        return SessionContinuity(
            active_project_id=active,
            last_conversation_summary=last_summary,
            priorities=interests[:5],
        )

    async def set_active_project(self, project_id: str | None) -> None:
        await self._set_state("active_project_id", project_id or "")
        if project_id:
            from sage.projects.manager import ProjectManager

            pm = self._container.try_resolve(ProjectManager)
            if pm:
                with contextlib.suppress(Exception):
                    await pm.touch(project_id)

    async def get_active_project_id(self) -> str | None:
        val = await self._get_state("active_project_id")
        return val or None

    async def record_interest(self, topic: str, *, weight: float = 0.1) -> None:
        topic = topic.strip()
        if not topic:
            return
        raw = await self._get_state("interests_json")
        data: dict[str, float] = {}
        if raw:
            try:
                import json

                data = {str(k): float(v) for k, v in json.loads(raw).items()}
            except Exception:
                data = {}
        key = topic.lower()[:80]
        data[key] = min(1.0, data.get(key, 0.0) + weight)
        # keep top 50
        ranked = sorted(data.items(), key=lambda x: x[1], reverse=True)[:50]
        import json

        await self._set_state("interests_json", json.dumps(dict(ranked)))

    async def suggestions(self, *, limit: int = 10) -> list[ProactiveSuggestion]:
        rows = await self.db.fetchall(
            """
            SELECT * FROM proactive_suggestions
            WHERE status = 'open'
            ORDER BY priority DESC, created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [self._row_to_suggestion(r) for r in rows]

    async def generate_suggestions(self) -> list[ProactiveSuggestion]:
        """Create suggestion rows from fused context (never auto-executes)."""
        created: list[ProactiveSuggestion] = []
        fused = await self.fuse()

        # Stale projects
        now = datetime.now(UTC)
        for p in fused.active_projects[:10]:
            last = p.get("last_accessed_at") or p.get("updated_at")
            if not last:
                continue
            try:
                ts = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
                age_days = (now - ts).total_seconds() / 86400.0
            except Exception:
                age_days = 0
            if age_days >= 7:
                s = await self._add_suggestion(
                    title=f"Project «{p.get('name')}» needs attention",
                    body=(
                        f"You haven't updated «{p.get('name')}» in about {age_days:.0f} days. "
                        "Consider reviewing progress, risks, or next tasks."
                    ),
                    category="project",
                    priority=min(0.9, 0.4 + age_days / 30.0),
                    related_project_id=p.get("id"),
                )
                if s:
                    created.append(s)

        # Pending approvals
        if fused.pending_approvals:
            s = await self._add_suggestion(
                title=f"{len(fused.pending_approvals)} pending approval(s)",
                body="Sensitive actions are waiting for your decision. Review with `sage approve`.",
                category="approval",
                priority=0.85,
            )
            if s:
                created.append(s)

        # Unfinished workflows
        if fused.running_workflows:
            s = await self._add_suggestion(
                title=f"{len(fused.running_workflows)} unfinished workflow(s)",
                body="There are workflows still running, paused, or waiting for approval.",
                category="workflow",
                priority=0.8,
            )
            if s:
                created.append(s)

        # Weather / agriculture interest
        interests = [i.lower() for i in fused.long_term_interests]
        if any(k in " ".join(interests) for k in ("agriculture", "farm", "irrigation", "crop")):
            s = await self._add_suggestion(
                title="Irrigation may need a weather-aware review",
                body=(
                    "Given your agriculture focus, consider running the morning farm briefing "
                    "workflow before the next irrigation cycle."
                ),
                category="agriculture",
                priority=0.55,
            )
            if s:
                created.append(s)

        # Daily goals without progress
        for g in fused.goals:
            if g.get("horizon") == "daily" and float(g.get("progress") or 0) < 0.1:
                s = await self._add_suggestion(
                    title=f"Daily goal open: {g.get('title')}",
                    body="This daily goal has little recorded progress. Want a plan or reminder?",
                    category="goal",
                    priority=0.6,
                    related_goal_id=g.get("id"),
                )
                if s:
                    created.append(s)
                break

        log.info("context.suggestions_generated", count=len(created))
        return created

    async def dismiss_suggestion(self, suggestion_id: str) -> bool:
        cur = await self.db.execute(
            """
            UPDATE proactive_suggestions
            SET status = 'dismissed', dismissed_at = ?
            WHERE id = ? AND status = 'open'
            """,
            (utcnow_iso(), suggestion_id),
        )
        return (cur.rowcount or 0) > 0

    async def snapshot(self, *, kind: str = "session") -> ContextSnapshot:
        fused = self._cached or await self.fuse()
        snap = ContextSnapshot(kind=kind, payload=fused.model_dump())
        await self.db.execute(
            """
            INSERT INTO context_snapshots (id, kind, payload, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (snap.id, snap.kind, self.dumps(snap.payload), snap.created_at),
        )
        # prune old
        await self.db.execute(
            """
            DELETE FROM context_snapshots WHERE id NOT IN (
                SELECT id FROM context_snapshots ORDER BY created_at DESC LIMIT 100
            )
            """
        )
        return snap

    async def bootstrap_session(self) -> UnifiedContext:
        """Called on engine start — restore continuity and refresh suggestions."""
        ctx = await self.fuse()
        try:
            await self.generate_suggestions()
            ctx = await self.fuse()
        except Exception:
            log.exception("context.bootstrap_suggestions_failed")
        await self.snapshot(kind="bootstrap")
        log.info(
            "context.session_bootstrapped",
            projects=len(ctx.active_projects),
            goals=len(ctx.goals),
            suggestions=len(ctx.suggestions),
            pending_approvals=len(ctx.pending_approvals),
        )
        return ctx

    # --- internals ---

    def _environment(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        month = now.month
        if month in (12, 1, 2):
            season = "winter"
        elif month in (3, 4, 5):
            season = "spring"
        elif month in (6, 7, 8):
            season = "summer"
        else:
            season = "autumn"
        return {
            "utc_now": utcnow_iso(),
            "weekday": now.strftime("%A"),
            "season": season,
            "hour_utc": now.hour,
        }

    def _summarize(self, ctx: UnifiedContext) -> str:
        bits = []
        if ctx.active_projects:
            bits.append(
                "Projects: " + ", ".join(p.get("name", "?") for p in ctx.active_projects[:3])
            )
        if ctx.priorities:
            bits.append("Priorities: " + "; ".join(ctx.priorities[:3]))
        if ctx.pending_approvals:
            bits.append(f"{len(ctx.pending_approvals)} pending approval(s)")
        if ctx.running_workflows:
            bits.append(f"{len(ctx.running_workflows)} open workflow(s)")
        if ctx.long_term_interests:
            bits.append("Interests: " + ", ".join(ctx.long_term_interests[:4]))
        env = ctx.environment
        bits.append(f"{env.get('weekday')} · {env.get('season')}")
        return " · ".join(bits) if bits else "No active context yet."

    async def _load_interests(self) -> list[str]:
        raw = await self._get_state("interests_json")
        interests: list[str] = []
        if raw:
            try:
                import json

                data = json.loads(raw)
                interests = [k for k, _ in sorted(data.items(), key=lambda x: -float(x[1]))]
            except Exception:
                interests = []
        # merge learning patterns
        try:
            rows = await self.db.fetchall(
                """
                SELECT signature, description, confidence FROM learned_patterns
                WHERE pattern_type IN ('domain_interest', 'workflow_usage')
                ORDER BY confidence DESC LIMIT 10
                """
            )
            for r in rows:
                sig = str(r["signature"]).replace("_", " ")
                if sig not in interests:
                    interests.append(sig)
        except Exception:
            pass
        return interests[:15]

    async def _add_suggestion(
        self,
        *,
        title: str,
        body: str,
        category: str,
        priority: float,
        related_project_id: str | None = None,
        related_goal_id: str | None = None,
    ) -> ProactiveSuggestion | None:
        # de-dupe open suggestions with same title
        existing = await self.db.fetchone(
            """
            SELECT id FROM proactive_suggestions
            WHERE status = 'open' AND title = ?
            """,
            (title,),
        )
        if existing:
            return None
        s = ProactiveSuggestion(
            id=new_id("sugg"),
            title=title,
            body=body,
            category=category,
            priority=priority,
            related_project_id=related_project_id,
            related_goal_id=related_goal_id,
        )
        await self.db.execute(
            """
            INSERT INTO proactive_suggestions (
                id, title, body, category, priority, status,
                related_project_id, related_goal_id, metadata, created_at,
                dismissed_at, acted_at
            ) VALUES (?, ?, ?, ?, ?, 'open', ?, ?, '{}', ?, NULL, NULL)
            """,
            (
                s.id,
                s.title,
                s.body,
                s.category,
                s.priority,
                s.related_project_id,
                s.related_goal_id,
                s.created_at,
            ),
        )
        return s

    async def _get_state(self, key: str) -> str | None:
        row = await self.db.fetchone("SELECT value FROM context_state WHERE key = ?", (key,))
        return row["value"] if row else None

    async def _set_state(self, key: str, value: str) -> None:
        await self.db.execute(
            """
            INSERT INTO context_state (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, utcnow_iso()),
        )

    def _row_to_suggestion(self, row: Any) -> ProactiveSuggestion:
        return ProactiveSuggestion(
            id=row["id"],
            title=row["title"],
            body=row["body"],
            category=row["category"],
            priority=float(row["priority"]),
            status=row["status"],
            related_project_id=row["related_project_id"],
            related_goal_id=row["related_goal_id"],
            metadata=self.loads(row["metadata"], {}),
            created_at=row["created_at"],
            dismissed_at=row["dismissed_at"],
            acted_at=row["acted_at"],
        )

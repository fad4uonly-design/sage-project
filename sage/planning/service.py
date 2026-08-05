"""Planning engine implementation."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.db.connection import Database
from sage.db.repository import BaseRepository
from sage.logging import get_logger
from sage.planning.interfaces import PlanningEngine
from sage.planning.models import (
    Goal,
    GoalStatus,
    Plan,
    PlanProgress,
    PlanStatus,
    PlanStep,
    Task,
    TaskStatus,
)
from sage.utils.time import utcnow_iso

log = get_logger(__name__)


class DefaultPlanningEngine(BaseRepository):
    def __init__(self, db: Database) -> None:
        super().__init__(db)

    async def create_goal(self, description: str, **kwargs: Any) -> Goal:
        goal = Goal(
            description=description,
            priority=float(kwargs.get("priority", 0.5)),
            metadata=dict(kwargs.get("metadata") or {}),
        )
        await self.db.execute(
            """
            INSERT INTO goals (id, description, status, priority, metadata, created_at, updated_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                goal.id,
                goal.description,
                goal.status.value,
                goal.priority,
                self.dumps(goal.metadata),
                goal.created_at,
                goal.updated_at,
            ),
        )
        log.info("planning.goal_created", id=goal.id)
        return goal

    async def plan(self, goal_id: str) -> Plan:
        row = await self.db.fetchone("SELECT * FROM goals WHERE id = ?", (goal_id,))
        if row is None:
            raise KeyError(f"Goal not found: {goal_id}")

        description = row["description"]
        steps = self._decompose(description)
        plan = Plan(
            goal_id=goal_id,
            title=f"Plan: {description[:80]}",
            status=PlanStatus.ACTIVE,
            steps=steps,
        )
        await self.db.execute(
            """
            INSERT INTO plans (id, goal_id, title, status, steps, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan.id,
                plan.goal_id,
                plan.title,
                plan.status.value,
                self.dumps([s.model_dump() for s in plan.steps]),
                plan.created_at,
                plan.updated_at,
            ),
        )

        # Materialize tasks
        for step in plan.steps:
            task = Task(plan_id=plan.id, title=step.title, priority=max(0.1, 1.0 - step.index * 0.1))
            await self.db.execute(
                """
                INSERT INTO tasks (id, plan_id, title, status, priority, due_at, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, NULL, '{}', ?, ?)
                """,
                (
                    task.id,
                    task.plan_id,
                    task.title,
                    task.status.value,
                    task.priority,
                    task.created_at,
                    task.updated_at,
                ),
            )

        log.info("planning.plan_created", id=plan.id, goal_id=goal_id, steps=len(steps))
        return plan

    async def prioritize(self, task_ids: Sequence[str]) -> list[str]:
        if not task_ids:
            return []
        placeholders = ",".join("?" for _ in task_ids)
        rows = await self.db.fetchall(
            f"SELECT id, priority FROM tasks WHERE id IN ({placeholders})",
            tuple(task_ids),
        )
        ranked = sorted(rows, key=lambda r: float(r["priority"]), reverse=True)
        # Keep unknown ids at end in original order
        known = {r["id"] for r in ranked}
        result = [r["id"] for r in ranked]
        for tid in task_ids:
            if tid not in known:
                result.append(tid)
        return result

    async def track(self, plan_id: str) -> PlanProgress:
        row = await self.db.fetchone("SELECT * FROM plans WHERE id = ?", (plan_id,))
        if row is None:
            raise KeyError(f"Plan not found: {plan_id}")
        steps_data = self.loads(row["steps"], [])
        total = len(steps_data) if steps_data else 0
        # Prefer live task statuses
        task_rows = await self.db.fetchall(
            "SELECT status FROM tasks WHERE plan_id = ?",
            (plan_id,),
        )
        if task_rows:
            total = len(task_rows)
            done = sum(1 for t in task_rows if t["status"] == TaskStatus.DONE.value)
        else:
            done = sum(
                1
                for s in steps_data
                if (s.get("status") if isinstance(s, dict) else None) == TaskStatus.DONE.value
            )
        percent = (done / total * 100.0) if total else 0.0
        return PlanProgress(
            plan_id=plan_id,
            status=PlanStatus(row["status"]),
            total_steps=total,
            done_steps=done,
            percent_complete=round(percent, 1),
        )

    def _decompose(self, description: str) -> list[PlanStep]:
        """Heuristic multi-step decomposition — improved by LLM in later phases."""
        templates = [
            ("Clarify objective", f"Define success criteria for: {description}"),
            ("Gather inputs", "Collect required information, resources, and constraints."),
            ("Design approach", "Choose a strategy and break work into actionable units."),
            ("Execute", "Perform the highest-leverage actions first."),
            ("Review & adjust", "Measure outcomes, capture lessons, update the plan."),
        ]
        # Domain spice
        lower = description.lower()
        if any(w in lower for w in ("study", "learn", "exam", "course")):
            templates = [
                ("Assess current level", "Identify strengths and gaps."),
                ("Build syllabus", "Sequence topics from foundations to advanced."),
                ("Schedule sessions", "Allocate daily/weekly study blocks."),
                ("Practice & test", "Use active recall and practice exams."),
                ("Review mistakes", "Consolidate weak areas into long-term memory."),
            ]
        elif any(w in lower for w in ("farm", "crop", "agriculture", "harvest")):
            templates = [
                ("Assess land & season", "Check soil, climate, and calendar windows."),
                ("Select crops/inputs", "Choose varieties, fertilizers, irrigation plan."),
                ("Prepare & plant", "Field prep, planting, initial care."),
                ("Monitor growth", "Pests, water, nutrients — weekly checks."),
                ("Harvest & review", "Yield measurement and season retrospective."),
            ]
        elif any(w in lower for w in ("business", "launch", "startup", "product")):
            templates = [
                ("Problem & customer", "Validate the pain and target segment."),
                ("Offer design", "Define value proposition and pricing."),
                ("MVP build", "Ship the smallest useful version."),
                ("Go-to-market", "Channels, messaging, first customers."),
                ("Measure & iterate", "KPIs, feedback loops, next bet."),
            ]

        return [
            PlanStep(index=i, title=title, detail=detail)
            for i, (title, detail) in enumerate(templates)
        ]


class PlanningModule(BaseModule):
    name = "planning"
    version = "0.1.0"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._engine: DefaultPlanningEngine | None = None

    async def _on_initialize(self) -> None:
        db = self.container.resolve(Database)
        self._engine = DefaultPlanningEngine(db)
        self.container.register_instance(PlanningEngine, self._engine)  # type: ignore[type-abstract]
        self.container.register_instance(DefaultPlanningEngine, self._engine)

    async def _on_health(self) -> HealthStatus | None:
        if self._engine is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        return HealthStatus.healthy(self.name, "ok")

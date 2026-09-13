"""
Reflection Engine.

Reviews completed workflows and audit trails to surface optimizations,
repeated failures, skill gaps, and knowledge-graph opportunities.
"""

from __future__ import annotations

import contextlib
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from sage.db.connection import Database
from sage.db.repository import BaseRepository
from sage.logging import get_logger
from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso

log = get_logger(__name__)


class Reflection(BaseModel):
    id: str = Field(default_factory=lambda: new_id("refl"))
    kind: str
    summary: str
    findings: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utcnow_iso)

    def format(self) -> str:
        lines = [
            f"### Reflection ({self.kind})",
            self.summary,
            "",
            "**Findings:**",
        ]
        lines.extend(f"- {f}" for f in self.findings or ["(none)"])
        lines += ["", "**Recommendations:**"]
        lines.extend(f"- {r}" for r in self.recommendations or ["(none)"])
        lines.append(f"\n_Confidence: {self.confidence:.2f}_")
        return "\n".join(lines)


@runtime_checkable
class ReflectionEngine(Protocol):
    async def reflect(self) -> Reflection: ...

    async def list_recent(self, *, limit: int = 20) -> list[Reflection]: ...


class DefaultReflectionEngine(BaseRepository):
    def __init__(self, db: Database, container: Any) -> None:
        super().__init__(db)
        self._container = container

    async def reflect(self) -> Reflection:
        findings: list[str] = []
        recommendations: list[str] = []
        refs: list[str] = []
        confidence = 0.55

        # Workflow outcomes
        try:
            rows = await self.db.fetchall(
                """
                SELECT status, COUNT(*) AS n FROM workflow_runs
                GROUP BY status
                """
            )
            by_status = {r["status"]: int(r["n"]) for r in rows}
            total = sum(by_status.values()) or 1
            failed = by_status.get("failed", 0)
            succeeded = by_status.get("succeeded", 0)
            waiting = by_status.get("waiting_approval", 0)
            findings.append(
                f"Workflows: {succeeded} succeeded, {failed} failed, "
                f"{waiting} waiting approval (n={total})"
            )
            if failed / total >= 0.25 and failed >= 2:
                findings.append("Elevated workflow failure rate detected")
                recommendations.append(
                    "Review failed workflow step audits; add retries or fix flaky tools/skills"
                )
                confidence += 0.1
            if waiting:
                recommendations.append(
                    f"Clear {waiting} workflow(s) blocked on approval to unblock automation"
                )
        except Exception:
            findings.append("Workflow stats unavailable")

        # Repeated step failures from audit
        try:
            rows = await self.db.fetchall(
                """
                SELECT summary, COUNT(*) AS n FROM execution_audit
                WHERE status IN ('error', 'step_failed', 'failed')
                GROUP BY summary
                HAVING n >= 2
                ORDER BY n DESC LIMIT 5
                """
            )
            for r in rows:
                findings.append(f"Repeated issue (×{r['n']}): {r['summary']}")
                refs.append(str(r["summary"])[:80])
            if rows:
                recommendations.append(
                    "Create a targeted skill or tool fix for the most repeated failure"
                )
                confidence += 0.05
        except Exception:
            pass

        # Skill usage gaps
        try:
            rows = await self.db.fetchall(
                """
                SELECT skill_id, COUNT(*) AS n FROM execution_audit
                WHERE skill_id IS NOT NULL AND skill_id != ''
                GROUP BY skill_id ORDER BY n DESC LIMIT 10
                """
            )
            if rows:
                top = ", ".join(f"{r['skill_id']}({r['n']})" for r in rows[:3])
                findings.append(f"Most used skills: {top}")
            else:
                findings.append("Little skill invocation history yet")
                recommendations.append(
                    "Encourage skill-library usage for recurring analysis/planning tasks"
                )
        except Exception:
            pass

        # Knowledge graph growth opportunity
        try:
            ent = await self.db.scalar(
                "SELECT COUNT(*) FROM kg_entities WHERE deleted_at IS NULL"
            )
            edges = await self.db.scalar(
                "SELECT COUNT(*) FROM kg_edges WHERE deleted_at IS NULL"
            )
            ent_n, edge_n = int(ent or 0), int(edges or 0)
            findings.append(f"Knowledge graph size: {ent_n} entities, {edge_n} edges")
            if ent_n > 0 and edge_n / max(ent_n, 1) < 0.5:
                recommendations.append(
                    "KG is entity-heavy vs relations — run extract_and_merge on key documents"
                )
                confidence += 0.05
        except Exception:
            pass

        # Confidence calibration hint from decision audits
        try:
            rows = await self.db.fetchall(
                """
                SELECT confidence FROM execution_audit
                WHERE confidence IS NOT NULL
                ORDER BY created_at DESC LIMIT 50
                """
            )
            if len(rows) >= 5:
                vals = [float(r["confidence"]) for r in rows if r["confidence"] is not None]
                avg = sum(vals) / len(vals)
                findings.append(f"Recent average recorded confidence: {avg:.2f}")
                if avg > 0.85:
                    recommendations.append(
                        "Confidence may be over-calibrated — include more contrary evidence in traces"
                    )
                elif avg < 0.45:
                    recommendations.append(
                        "Low average confidence — improve retrieval fusion before high-stakes decisions"
                    )
        except Exception:
            pass

        # Learning patterns
        try:
            rows = await self.db.fetchall(
                """
                SELECT pattern_type, COUNT(*) AS n FROM learned_patterns
                GROUP BY pattern_type
                """
            )
            if rows:
                findings.append(
                    "Learning patterns: "
                    + ", ".join(f"{r['pattern_type']}={r['n']}" for r in rows)
                )
        except Exception:
            pass

        if not recommendations:
            recommendations.append(
                "System looks stable — continue capturing workflows and user corrections"
            )

        summary = (
            "Reflection over recent executions, audits, skills, and knowledge graph health."
        )
        reflection = Reflection(
            kind="system",
            summary=summary,
            findings=findings,
            recommendations=recommendations,
            confidence=min(0.9, confidence),
            source_refs=refs[:10],
        )
        await self._persist(reflection)

        # Feed learning engine lightly
        from sage.learning.interfaces import LearningEngine
        from sage.learning.models import Observation, ObservationKind

        learn = self._container.try_resolve(LearningEngine)
        if learn:
            with contextlib.suppress(Exception):
                await learn.observe(
                    Observation(
                        kind=ObservationKind.SUCCESS
                        if "failure" not in summary.lower()
                        else ObservationKind.EXTERNAL,
                        content="Reflection: " + "; ".join(findings[:3]),
                        metadata={"reflection_id": reflection.id},
                    )
                )

        log.info(
            "reflection.complete",
            id=reflection.id,
            findings=len(findings),
            recommendations=len(recommendations),
        )
        return reflection

    async def list_recent(self, *, limit: int = 20) -> list[Reflection]:
        rows = await self.db.fetchall(
            "SELECT * FROM reflections ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [self._row_to_reflection(r) for r in rows]

    async def _persist(self, reflection: Reflection) -> None:
        await self.db.execute(
            """
            INSERT INTO reflections (
                id, kind, summary, findings, recommendations, confidence,
                source_refs, metadata, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reflection.id,
                reflection.kind,
                reflection.summary,
                self.dumps(reflection.findings),
                self.dumps(reflection.recommendations),
                reflection.confidence,
                self.dumps(reflection.source_refs),
                self.dumps(reflection.metadata),
                reflection.created_at,
            ),
        )

    def _row_to_reflection(self, row: Any) -> Reflection:
        return Reflection(
            id=row["id"],
            kind=row["kind"],
            summary=row["summary"],
            findings=self.loads(row["findings"], []),
            recommendations=self.loads(row["recommendations"], []),
            confidence=float(row["confidence"]),
            source_refs=self.loads(row["source_refs"], []),
            metadata=self.loads(row["metadata"], {}),
            created_at=row["created_at"],
        )

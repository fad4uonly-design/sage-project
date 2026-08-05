"""
Knowledge Discovery Engine.

Complements Reflection (which reviews executions) by mining the Knowledge Graph,
memories, and patterns for hidden relationships, contradictions, gaps, and trends.
Suggestions only — never auto-executes changes.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from sage.db.connection import Database
from sage.db.repository import BaseRepository
from sage.logging import get_logger
from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso

log = get_logger(__name__)


class InsightKind(str):
    RELATIONSHIP = "relationship"
    PATTERN = "pattern"
    HYPOTHESIS = "hypothesis"
    OPTIMIZATION = "optimization"
    MISSING_KNOWLEDGE = "missing_knowledge"
    CONTRADICTION = "contradiction"
    TREND = "trend"
    WORKFLOW = "workflow"


class DiscoveryInsight(BaseModel):
    id: str = Field(default_factory=lambda: new_id("disc"))
    kind: str
    title: str
    body: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utcnow_iso)

    def format(self) -> str:
        lines = [
            f"### Discovery · {self.kind}",
            f"**{self.title}**",
            "",
            self.body,
        ]
        if self.evidence:
            lines += ["", "**Evidence:**"]
            lines.extend(f"- {e}" for e in self.evidence[:8])
        if self.recommendations:
            lines += ["", "**Suggestions:**"]
            lines.extend(f"- {r}" for r in self.recommendations[:6])
        lines.append(f"\n_Confidence: {self.confidence:.2f}_")
        return "\n".join(lines)


@runtime_checkable
class DiscoveryEngine(Protocol):
    async def discover(self, *, limit: int = 20) -> list[DiscoveryInsight]: ...

    async def list_recent(self, *, limit: int = 30) -> list[DiscoveryInsight]: ...


class DefaultDiscoveryEngine(BaseRepository):
    def __init__(self, db: Database, container: Any) -> None:
        super().__init__(db)
        self._container = container

    async def discover(self, *, limit: int = 20) -> list[DiscoveryInsight]:
        insights: list[DiscoveryInsight] = []
        insights.extend(await self._hub_entities())
        insights.extend(await self._sparse_entities())
        insights.extend(await self._relation_patterns())
        insights.extend(await self._agriculture_hypotheses())
        insights.extend(await self._business_hypotheses())
        insights.extend(await self._memory_kg_gaps())
        insights.extend(await self._contradiction_hints())
        insights.extend(await self._workflow_recommendations())

        # Rank by confidence and cap
        insights.sort(key=lambda i: i.confidence, reverse=True)
        insights = insights[:limit]
        for ins in insights:
            await self._persist(ins)
            await self._maybe_suggest(ins)

        log.info("discovery.complete", count=len(insights))
        return insights

    async def list_recent(self, *, limit: int = 30) -> list[DiscoveryInsight]:
        # Prefer dedicated table if present; else empty
        try:
            rows = await self.db.fetchall(
                """
                SELECT * FROM discovery_insights
                ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            )
            return [self._row_to_insight(r) for r in rows]
        except Exception:
            return []

    # --- miners ---

    async def _hub_entities(self) -> list[DiscoveryInsight]:
        try:
            rows = await self.db.fetchall(
                """
                SELECT e.id, e.name, e.entity_type,
                       (SELECT COUNT(*) FROM kg_edges g
                        WHERE g.deleted_at IS NULL
                          AND (g.source_id = e.id OR g.target_id = e.id)) AS deg
                FROM kg_entities e
                WHERE e.deleted_at IS NULL
                ORDER BY deg DESC
                LIMIT 5
                """
            )
        except Exception:
            return []
        if not rows or int(rows[0]["deg"] or 0) < 2:
            return []
        top = rows[0]
        others = ", ".join(f"{r['name']}({r['deg']})" for r in rows[:4])
        return [
            DiscoveryInsight(
                kind="pattern",
                title=f"Central concept: {top['name']}",
                body=(
                    f"«{top['name']}» ({top['entity_type']}) is highly connected "
                    f"(degree {top['deg']}). Other hubs: {others}."
                ),
                confidence=min(0.85, 0.45 + int(top["deg"]) * 0.05),
                evidence=[f"{r['name']}: degree {r['deg']}" for r in rows[:5]],
                recommendations=[
                    f"Keep «{top['name']}» well-documented; new facts should link to it when relevant",
                    "Review hub neighborhoods for missing domain edges",
                ],
                metadata={"entity_id": top["id"]},
            )
        ]

    async def _sparse_entities(self) -> list[DiscoveryInsight]:
        try:
            rows = await self.db.fetchall(
                """
                SELECT e.id, e.name, e.entity_type
                FROM kg_entities e
                WHERE e.deleted_at IS NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM kg_edges g
                    WHERE g.deleted_at IS NULL
                      AND (g.source_id = e.id OR g.target_id = e.id)
                  )
                LIMIT 15
                """
            )
        except Exception:
            return []
        if len(rows) < 3:
            return []
        names = [r["name"] for r in rows[:8]]
        return [
            DiscoveryInsight(
                kind="missing_knowledge",
                title=f"{len(rows)}+ isolated entities in the graph",
                body=(
                    "Several entities have no relationships yet. Isolated nodes reduce "
                    "reasoning quality. Examples: " + ", ".join(names) + "."
                ),
                confidence=0.7,
                evidence=names,
                recommendations=[
                    "Run document ingest / extract_and_merge on related notes",
                    "Manually link orphans to hub concepts (is_a, requires, related_to)",
                ],
            )
        ]

    async def _relation_patterns(self) -> list[DiscoveryInsight]:
        try:
            rows = await self.db.fetchall(
                """
                SELECT relation, COUNT(*) AS n FROM kg_edges
                WHERE deleted_at IS NULL
                GROUP BY relation ORDER BY n DESC LIMIT 8
                """
            )
        except Exception:
            return []
        if not rows:
            return []
        top = ", ".join(f"{r['relation']}×{r['n']}" for r in rows[:5])
        return [
            DiscoveryInsight(
                kind="pattern",
                title="Dominant relationship types",
                body=f"Most common edge types in your graph: {top}.",
                confidence=0.65,
                evidence=[f"{r['relation']}: {r['n']}" for r in rows],
                recommendations=[
                    "If one relation dominates, diversify with causal/part_of/requires edges where true",
                ],
            )
        ]

    async def _agriculture_hypotheses(self) -> list[DiscoveryInsight]:
        """Domain-aware hypothesis from co-occurring agri concepts."""
        try:
            # Look for tomato/water/irrigation/blight style clusters
            keys = ("tomato", "water", "irrigation", "blight", "soil", "fertilizer", "crop")
            present = []
            for k in keys:
                row = await self.db.fetchone(
                    """
                    SELECT name FROM kg_entities
                    WHERE deleted_at IS NULL AND canonical_name LIKE ?
                    LIMIT 1
                    """,
                    (f"%{k}%",),
                )
                if row:
                    present.append(row["name"])
        except Exception:
            return []
        if len(present) < 3:
            return []
        has_water = any("water" in p.lower() or "irrigation" in p.lower() for p in present)
        has_disease = any("blight" in p.lower() or "pest" in p.lower() for p in present)
        insights = []
        if has_water and has_disease:
            insights.append(
                DiscoveryInsight(
                    kind="hypothesis",
                    title="Irrigation efficiency vs disease pressure",
                    body=(
                        "Your graph links crop, water/irrigation, and disease concepts. "
                        "A testable hypothesis: switching to drip irrigation may reduce "
                        "leaf wetness (and fungal risk) while maintaining soil moisture."
                    ),
                    confidence=0.58,
                    evidence=present,
                    recommendations=[
                        "Run morning_farm_briefing workflow before changing irrigation",
                        "Log disease incidents vs irrigation method for two weeks",
                        "Compare water use (Finance expense forecast) against yield notes",
                    ],
                    metadata={"domain": "agriculture"},
                )
            )
        if has_water:
            insights.append(
                DiscoveryInsight(
                    kind="optimization",
                    title="Water-related cost tracking opportunity",
                    body=(
                        "Water/irrigation concepts are present. Pairing agriculture workflows "
                        "with finance expense forecasts can surface cost–health trade-offs."
                    ),
                    confidence=0.55,
                    evidence=present,
                    recommendations=[
                        "After irrigation plan, run finance expense forecast collaboration",
                    ],
                    metadata={"domain": "agriculture"},
                )
            )
        return insights

    async def _business_hypotheses(self) -> list[DiscoveryInsight]:
        try:
            row = await self.db.fetchone(
                """
                SELECT COUNT(*) AS n FROM kg_entities
                WHERE deleted_at IS NULL AND entity_type IN
                  ('company','customer','market','campaign','revenue','competitor')
                """
            )
            n = int(row["n"] or 0) if row else 0
        except Exception:
            return []
        if n < 4:
            return []
        return [
            DiscoveryInsight(
                kind="trend",
                title="Business entity cluster is forming",
                body=(
                    f"Found {n} business-typed entities. The BI suite can now ground "
                    "SWOT, pricing, and KPI workflows in graph structure rather than "
                    "generic templates alone."
                ),
                confidence=0.6,
                evidence=[f"business_typed_entities={n}"],
                recommendations=[
                    "Link campaigns → customers → revenue explicitly",
                    "Run business_expansion_report on an active project",
                ],
                metadata={"domain": "business"},
            )
        ]

    async def _memory_kg_gaps(self) -> list[DiscoveryInsight]:
        try:
            mem_n = int(
                await self.db.scalar(
                    "SELECT COUNT(*) FROM memories WHERE deleted_at IS NULL"
                )
                or 0
            )
            ent_n = int(
                await self.db.scalar(
                    "SELECT COUNT(*) FROM kg_entities WHERE deleted_at IS NULL"
                )
                or 0
            )
        except Exception:
            return []
        if mem_n < 3:
            return []
        if ent_n > 0 and mem_n > ent_n * 2:
            return [
                DiscoveryInsight(
                    kind="missing_knowledge",
                    title="Memories outpace graph structure",
                    body=(
                        f"You have {mem_n} memories vs {ent_n} graph entities. "
                        "Important facts may not be linked for multi-hop reasoning."
                    ),
                    confidence=0.62,
                    evidence=[f"memories={mem_n}", f"entities={ent_n}"],
                    recommendations=[
                        "Re-ingest key notes so extract_and_merge can build edges",
                        "When remembering critical facts, include clear subject–relation–object phrasing",
                    ],
                )
            ]
        return []

    async def _contradiction_hints(self) -> list[DiscoveryInsight]:
        """Lightweight contradiction: same pair with opposing relation labels."""
        try:
            rows = await self.db.fetchall(
                """
                SELECT a.source_id, a.target_id, a.relation AS r1, b.relation AS r2
                FROM kg_edges a
                JOIN kg_edges b
                  ON a.source_id = b.source_id AND a.target_id = b.target_id
                 AND a.id < b.id
                WHERE a.deleted_at IS NULL AND b.deleted_at IS NULL
                  AND a.relation != b.relation
                LIMIT 20
                """
            )
        except Exception:
            return []
        opposing = {
            ("requires", "prevents"),
            ("causes", "prevents"),
            ("similar_to", "opposite_of"),
        }
        hits = []
        for r in rows:
            pair = tuple(sorted([r["r1"], r["r2"]]))
            if pair in opposing or (r["r1"], r["r2"]) in opposing:
                hits.append(f"{r['r1']} vs {r['r2']} on same node pair")
        if not hits:
            return []
        return [
            DiscoveryInsight(
                kind="contradiction",
                title="Possible conflicting relationships",
                body=(
                    "Some entity pairs carry relations that may conflict. "
                    "Review before high-stakes decisions."
                ),
                confidence=0.5,
                evidence=hits[:6],
                recommendations=[
                    "Inspect edge provenance and drop or version obsolete relations",
                ],
            )
        ]

    async def _workflow_recommendations(self) -> list[DiscoveryInsight]:
        try:
            rows = await self.db.fetchall(
                """
                SELECT definition_id, status, COUNT(*) AS n
                FROM workflow_runs
                GROUP BY definition_id, status
                """
            )
        except Exception:
            return []
        if not rows:
            return [
                DiscoveryInsight(
                    kind="workflow",
                    title="No workflow history yet",
                    body="Automation is available but unused. Discovery suggests trying a built-in workflow.",
                    confidence=0.55,
                    recommendations=[
                        "sage run-workflow morning_farm_briefing --task 'tomatoes'",
                        "sage run-workflow business_expansion_report --task 'new market'",
                    ],
                )
            ]
        return []

    async def _persist(self, insight: DiscoveryInsight) -> None:
        try:
            await self.db.execute(
                """
                INSERT INTO discovery_insights (
                    id, kind, title, body, confidence, evidence, recommendations,
                    metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    insight.id,
                    insight.kind,
                    insight.title,
                    insight.body,
                    insight.confidence,
                    self.dumps(insight.evidence),
                    self.dumps(insight.recommendations),
                    self.dumps(insight.metadata),
                    insight.created_at,
                ),
            )
        except Exception:
            # Table may not exist on partial migrate — ignore
            pass

    async def _maybe_suggest(self, insight: DiscoveryInsight) -> None:
        """Surface high-confidence discoveries as proactive suggestions (advisory)."""
        if insight.confidence < 0.6:
            return
        try:
            from sage.context.engine import CognitiveContextEngine

            cce = self._container.try_resolve(CognitiveContextEngine)
            if not cce:
                return
            # Use internal helper if available
            add = getattr(cce, "_add_suggestion", None)
            if callable(add):
                await add(
                    title=f"Discovery: {insight.title}",
                    body=insight.body[:400],
                    category="discovery",
                    priority=min(0.85, insight.confidence),
                )
        except Exception:
            pass

    def _row_to_insight(self, row: Any) -> DiscoveryInsight:
        return DiscoveryInsight(
            id=row["id"],
            kind=row["kind"],
            title=row["title"],
            body=row["body"],
            confidence=float(row["confidence"]),
            evidence=self.loads(row["evidence"], []),
            recommendations=self.loads(row["recommendations"], []),
            metadata=self.loads(row["metadata"], {}),
            created_at=row["created_at"],
        )

"""SQLite-backed knowledge graph with versioning and bidirectional edges."""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from typing import Any

from sage.db.connection import Database
from sage.db.repository import BaseRepository
from sage.events.bus import EventBus
from sage.events.events import Event
from sage.knowledge.graph.extract import TextExtractor
from sage.knowledge.graph.models import (
    Entity,
    EntityType,
    ExtractionResult,
    GraphEdge,
    GraphPath,
    GraphTriple,
    canonicalize,
)
from sage.logging import get_logger
from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso

log = get_logger(__name__)


class SQLiteKnowledgeGraph(BaseRepository):
    def __init__(self, db: Database, events: EventBus | None = None) -> None:
        super().__init__(db)
        self._events = events
        self._extractor = TextExtractor()

    # ------------------------------------------------------------------ entities

    async def upsert_entity(self, entity: Entity) -> Entity:
        if not entity.canonical_name:
            entity.canonical_name = canonicalize(entity.name)
        existing = await self.find_entity(entity.name, entity_type=None)
        # Prefer canonical match regardless of type for merge
        row = await self.db.fetchone(
            "SELECT * FROM kg_entities WHERE canonical_name = ? AND deleted_at IS NULL",
            (entity.canonical_name,),
        )
        now = utcnow_iso()
        if row:
            # Merge: bump confidence, fill description/type if richer
            eid = row["id"]
            new_conf = min(1.0, max(float(row["confidence"]), entity.confidence) + 0.02)
            new_type = row["entity_type"]
            if entity.entity_type != EntityType.CONCEPT and row["entity_type"] == EntityType.CONCEPT.value:
                new_type = entity.entity_type.value
            new_desc = entity.description or row["description"]
            props = {**self.loads(row["properties"], {}), **entity.properties}
            version = int(row["version"]) + 1
            await self.db.execute(
                """
                UPDATE kg_entities SET
                    name = ?, entity_type = ?, description = ?, confidence = ?,
                    properties = ?, version = ?, updated_at = ?,
                    source = COALESCE(?, source),
                    source_ref = COALESCE(?, source_ref)
                WHERE id = ?
                """,
                (
                    entity.name or row["name"],
                    new_type,
                    new_desc,
                    new_conf,
                    self.dumps(props),
                    version,
                    now,
                    entity.source,
                    entity.source_ref,
                    eid,
                ),
            )
            await self._version_entity(eid, version, reason="upsert_merge")
            updated = await self.get_entity(eid)
            assert updated is not None
            return updated

        entity.created_at = now
        entity.updated_at = now
        await self.db.execute(
            """
            INSERT INTO kg_entities (
                id, name, canonical_name, entity_type, description, confidence,
                source, source_ref, properties, version, created_at, updated_at, deleted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                entity.id,
                entity.name,
                entity.canonical_name,
                entity.entity_type.value,
                entity.description,
                entity.confidence,
                entity.source,
                entity.source_ref,
                self.dumps(entity.properties),
                entity.version,
                entity.created_at,
                entity.updated_at,
            ),
        )
        await self._version_entity(entity.id, entity.version, reason="create")
        log.debug("kg.entity_created", id=entity.id, name=entity.name)
        return entity

    async def get_entity(self, entity_id: str) -> Entity | None:
        row = await self.db.fetchone(
            "SELECT * FROM kg_entities WHERE id = ? AND deleted_at IS NULL",
            (entity_id,),
        )
        return self._row_to_entity(row) if row else None

    async def find_entity(
        self, name: str, *, entity_type: EntityType | None = None
    ) -> Entity | None:
        can = canonicalize(name)
        if entity_type:
            row = await self.db.fetchone(
                """
                SELECT * FROM kg_entities
                WHERE canonical_name = ? AND entity_type = ? AND deleted_at IS NULL
                """,
                (can, entity_type.value),
            )
        else:
            row = await self.db.fetchone(
                "SELECT * FROM kg_entities WHERE canonical_name = ? AND deleted_at IS NULL",
                (can,),
            )
        return self._row_to_entity(row) if row else None

    async def search_entities(self, query: str, *, limit: int = 20) -> list[Entity]:
        q = f"%{query.strip()}%"
        can = f"%{canonicalize(query)}%"
        rows = await self.db.fetchall(
            """
            SELECT * FROM kg_entities
            WHERE deleted_at IS NULL
              AND (name LIKE ? OR canonical_name LIKE ? OR IFNULL(description,'') LIKE ?)
            ORDER BY confidence DESC, name ASC
            LIMIT ?
            """,
            (q, can, q, limit),
        )
        return [self._row_to_entity(r) for r in rows]

    # ------------------------------------------------------------------ edges

    async def link(
        self,
        source: str | Entity,
        relation: str,
        target: str | Entity,
        *,
        confidence: float = 0.5,
        weight: float = 1.0,
        bidirectional: bool | None = None,
        source_ref: str | None = None,
        properties: dict[str, Any] | None = None,
        provenance: str | None = None,
    ) -> GraphEdge:
        src = await self._resolve_entity_ref(source)
        tgt = await self._resolve_entity_ref(target)
        if src.id == tgt.id:
            raise ValueError("Cannot link entity to itself")

        existing = await self.db.fetchone(
            """
            SELECT * FROM kg_edges
            WHERE source_id = ? AND target_id = ? AND relation = ? AND deleted_at IS NULL
            """,
            (src.id, tgt.id, relation),
        )
        now = utcnow_iso()
        bi = bool(bidirectional) if bidirectional is not None else False
        if existing:
            new_conf = min(1.0, max(float(existing["confidence"]), confidence) + 0.03)
            version = int(existing["version"]) + 1
            props = {**self.loads(existing["properties"], {}), **(properties or {})}
            await self.db.execute(
                """
                UPDATE kg_edges SET
                    confidence = ?, weight = ?, bidirectional = ?,
                    properties = ?, version = ?, updated_at = ?,
                    source_ref = COALESCE(?, source_ref)
                WHERE id = ?
                """,
                (
                    new_conf,
                    max(float(existing["weight"]), weight),
                    1 if (bi or existing["bidirectional"]) else 0,
                    self.dumps(props),
                    version,
                    now,
                    source_ref,
                    existing["id"],
                ),
            )
            edge = await self._get_edge(existing["id"])
            assert edge is not None
            return edge

        edge = GraphEdge(
            source_id=src.id,
            target_id=tgt.id,
            relation=relation,
            weight=weight,
            confidence=confidence,
            bidirectional=bi,
            source=provenance or "graph",
            source_ref=source_ref,
            properties=properties or {},
            created_at=now,
            updated_at=now,
        )
        await self.db.execute(
            """
            INSERT INTO kg_edges (
                id, source_id, target_id, relation, weight, confidence, bidirectional,
                source, source_ref, properties, version, created_at, updated_at, deleted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                edge.id,
                edge.source_id,
                edge.target_id,
                edge.relation,
                edge.weight,
                edge.confidence,
                1 if edge.bidirectional else 0,
                edge.source,
                edge.source_ref,
                self.dumps(edge.properties),
                edge.version,
                edge.created_at,
                edge.updated_at,
            ),
        )
        if self._events:
            await self._events.publish(
                Event(
                    type="knowledge.graph.edge_created",
                    payload={
                        "id": edge.id,
                        "source": src.name,
                        "relation": relation,
                        "target": tgt.name,
                    },
                    source="knowledge_graph",
                )
            )
        log.debug("kg.edge_created", relation=relation, src=src.name, tgt=tgt.name)
        return edge

    async def neighbors(
        self,
        entity_id: str,
        *,
        relation: str | None = None,
        direction: str = "both",
        limit: int = 50,
    ) -> list[GraphTriple]:
        clauses: list[str] = ["e.deleted_at IS NULL"]
        params: list[Any] = []
        dir_parts: list[str] = []
        if direction in ("out", "both"):
            dir_parts.append("e.source_id = ?")
            params.append(entity_id)
        if direction in ("in", "both"):
            dir_parts.append("e.target_id = ?")
            params.append(entity_id)
        if not dir_parts:
            dir_parts = ["e.source_id = ?", "e.target_id = ?"]
            params.extend([entity_id, entity_id])
        clauses.append(f"({' OR '.join(dir_parts)})")
        if relation:
            clauses.append("e.relation = ?")
            params.append(relation)
        params.append(limit)
        rows = await self.db.fetchall(
            f"""
            SELECT e.* FROM kg_edges e
            WHERE {' AND '.join(clauses)}
            ORDER BY e.confidence DESC
            LIMIT ?
            """,
            tuple(params),
        )
        return await self._edges_to_triples(rows)

    async def path(
        self,
        source_id: str,
        target_id: str,
        *,
        max_depth: int = 4,
    ) -> GraphPath | None:
        if source_id == target_id:
            ent = await self.get_entity(source_id)
            return GraphPath(nodes=[ent] if ent else [], edges=[], score=1.0)

        # BFS on undirected view of edges
        visited: set[str] = {source_id}
        # queue items: (node_id, node_path, edge_path)
        queue: deque[tuple[str, list[str], list[str]]] = deque([(source_id, [source_id], [])])

        while queue:
            node, npath, epath = queue.popleft()
            if len(npath) - 1 >= max_depth:
                continue
            triples = await self.neighbors(node, direction="both", limit=100)
            for t in triples:
                nxt = t.object.id if t.subject.id == node else t.subject.id
                # For outgoing-only subject→object when edge not bi and we arrived as target
                if t.subject.id == node:
                    nxt = t.object.id
                elif t.object.id == node:
                    if not t.edge.bidirectional and t.edge.relation not in {
                        "related_to",
                        "similar_to",
                        "opposite_of",
                    }:
                        # allow reverse traversal for path finding (knowledge is often undirected for search)
                        nxt = t.subject.id
                    else:
                        nxt = t.subject.id
                else:
                    continue
                if nxt in visited:
                    continue
                visited.add(nxt)
                new_npath = npath + [nxt]
                new_epath = epath + [t.edge.id]
                if nxt == target_id:
                    nodes: list[Entity] = []
                    for nid in new_npath:
                        ent = await self.get_entity(nid)
                        if ent:
                            nodes.append(ent)
                    edges: list[GraphEdge] = []
                    for eid in new_epath:
                        e = await self._get_edge(eid)
                        if e:
                            edges.append(e)
                    score = 1.0 / max(len(edges), 1)
                    return GraphPath(nodes=nodes, edges=edges, score=score)
                queue.append((nxt, new_npath, new_epath))
        return None

    async def query_relation(
        self,
        subject: str | None = None,
        relation: str | None = None,
        obj: str | None = None,
        *,
        limit: int = 50,
    ) -> list[GraphTriple]:
        clauses = ["e.deleted_at IS NULL"]
        params: list[Any] = []
        join_s = join_o = ""
        if subject:
            join_s = "JOIN kg_entities s ON s.id = e.source_id AND s.deleted_at IS NULL"
            clauses.append("(s.canonical_name = ? OR s.name LIKE ?)")
            can = canonicalize(subject)
            params.extend([can, f"%{subject}%"])
        if obj:
            join_o = "JOIN kg_entities o ON o.id = e.target_id AND o.deleted_at IS NULL"
            clauses.append("(o.canonical_name = ? OR o.name LIKE ?)")
            can = canonicalize(obj)
            params.extend([can, f"%{obj}%"])
        if relation:
            clauses.append("e.relation = ?")
            params.append(relation)
        params.append(limit)
        sql = f"""
            SELECT e.* FROM kg_edges e
            {join_s}
            {join_o}
            WHERE {' AND '.join(clauses)}
            ORDER BY e.confidence DESC
            LIMIT ?
        """
        rows = await self.db.fetchall(sql, tuple(params))
        return await self._edges_to_triples(rows)

    async def extract_and_merge(
        self,
        text: str,
        *,
        source: str = "extraction",
        source_ref: str | None = None,
        document_id: str | None = None,
        chunk_id: str | None = None,
        memory_id: str | None = None,
    ) -> ExtractionResult:
        raw = self._extractor.extract(text, source=source)
        entities: list[Entity] = []
        edges: list[GraphEdge] = []
        mentions = 0

        # Upsert entities
        can_to_entity: dict[str, Entity] = {}
        for can, ent in raw.entities.items():
            ent.source = source
            ent.source_ref = source_ref
            merged = await self.upsert_entity(ent)
            can_to_entity[can] = merged
            entities.append(merged)
            if document_id or chunk_id or memory_id:
                await self._add_mention(
                    merged.id,
                    document_id=document_id,
                    chunk_id=chunk_id,
                    memory_id=memory_id,
                    span_text=ent.name,
                    confidence=ent.confidence,
                )
                mentions += 1

        # Link triples
        for src_c, rel, tgt_c, conf in raw.triples:
            src_e = can_to_entity.get(src_c)
            tgt_e = can_to_entity.get(tgt_c)
            if not src_e or not tgt_e or src_e.id == tgt_e.id:
                continue
            edge = await self.link(

                src_e,
                rel,
                tgt_e,
                confidence=conf,
                source_ref=source_ref,
                provenance=source,
            )
            edges.append(edge)

        log.info(
            "kg.extract_merged",
            entities=len(entities),
            edges=len(edges),
            mentions=mentions,
            source=source,
        )
        return ExtractionResult(
            entities=entities,
            edges=edges,
            mentions=mentions,
            source_ref=source_ref,
        )

    async def subgraph(self, seed_ids: Sequence[str], *, depth: int = 1) -> list[GraphTriple]:
        seen_edges: set[str] = set()
        frontier = set(seed_ids)
        all_ids = set(seed_ids)
        triples: list[GraphTriple] = []
        for _ in range(max(depth, 0)):
            next_frontier: set[str] = set()
            for eid in frontier:
                neigh = await self.neighbors(eid, direction="both", limit=50)
                for t in neigh:
                    if t.edge.id in seen_edges:
                        continue
                    seen_edges.add(t.edge.id)
                    triples.append(t)
                    all_ids.add(t.subject.id)
                    all_ids.add(t.object.id)
                    if t.subject.id not in frontier:
                        next_frontier.add(t.subject.id)
                    if t.object.id not in frontier:
                        next_frontier.add(t.object.id)
            frontier = next_frontier - all_ids | (next_frontier & all_ids)
            frontier = next_frontier
        return triples

    async def stats(self) -> dict[str, Any]:
        entities = int(await self.db.scalar(
            "SELECT COUNT(*) FROM kg_entities WHERE deleted_at IS NULL"
        ) or 0)
        edges = int(await self.db.scalar(
            "SELECT COUNT(*) FROM kg_edges WHERE deleted_at IS NULL"
        ) or 0)
        types = await self.db.fetchall(
            """
            SELECT entity_type, COUNT(*) AS n FROM kg_entities
            WHERE deleted_at IS NULL GROUP BY entity_type ORDER BY n DESC
            """
        )
        return {
            "entities": entities,
            "edges": edges,
            "types": {r["entity_type"]: r["n"] for r in types},
        }

    # ------------------------------------------------------------------ helpers

    async def _resolve_entity_ref(self, ref: str | Entity) -> Entity:
        if isinstance(ref, Entity):
            if await self.get_entity(ref.id):
                return ref
            return await self.upsert_entity(ref)
        # id or name
        by_id = await self.get_entity(ref)
        if by_id:
            return by_id
        found = await self.find_entity(ref)
        if found:
            return found
        return await self.upsert_entity(Entity(name=ref, source="auto"))

    async def _get_edge(self, edge_id: str) -> GraphEdge | None:
        row = await self.db.fetchone(
            "SELECT * FROM kg_edges WHERE id = ? AND deleted_at IS NULL",
            (edge_id,),
        )
        return self._row_to_edge(row) if row else None

    async def _edges_to_triples(self, rows: list[Any]) -> list[GraphTriple]:
        triples: list[GraphTriple] = []
        for row in rows:
            edge = self._row_to_edge(row)
            subj = await self.get_entity(edge.source_id)
            obj = await self.get_entity(edge.target_id)
            if not subj or not obj:
                continue
            triples.append(
                GraphTriple(
                    subject=subj,
                    relation=edge.relation,
                    object=obj,
                    edge=edge,
                    confidence=edge.confidence,
                )
            )
        return triples

    def _row_to_entity(self, row: Any) -> Entity:
        return Entity(
            id=row["id"],
            name=row["name"],
            canonical_name=row["canonical_name"],
            entity_type=EntityType(row["entity_type"]),
            description=row["description"],
            confidence=row["confidence"],
            source=row["source"],
            source_ref=row["source_ref"],
            properties=self.loads(row["properties"], {}),
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            deleted_at=row["deleted_at"],
        )

    def _row_to_edge(self, row: Any) -> GraphEdge:
        return GraphEdge(
            id=row["id"],
            source_id=row["source_id"],
            target_id=row["target_id"],
            relation=row["relation"],
            weight=row["weight"],
            confidence=row["confidence"],
            bidirectional=bool(row["bidirectional"]),
            source=row["source"],
            source_ref=row["source_ref"],
            properties=self.loads(row["properties"], {}),
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            deleted_at=row["deleted_at"],
        )

    async def _version_entity(self, entity_id: str, version: int, *, reason: str) -> None:
        ent = await self.get_entity(entity_id)
        if not ent:
            return
        await self.db.execute(
            """
            INSERT INTO kg_entity_versions (id, entity_id, version, snapshot, changed_at, change_reason)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (new_id("ever"), entity_id, version, self.dumps(ent.model_dump()), utcnow_iso(), reason),
        )

    async def _add_mention(
        self,
        entity_id: str,
        *,
        document_id: str | None,
        chunk_id: str | None,
        memory_id: str | None,
        span_text: str | None,
        confidence: float,
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO kg_mentions
                (id, entity_id, document_id, chunk_id, memory_id, span_text, confidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("men"),
                entity_id,
                document_id,
                chunk_id,
                memory_id,
                span_text,
                confidence,
                utcnow_iso(),
            ),
        )

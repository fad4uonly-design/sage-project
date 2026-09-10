"""Knowledge manager — documents + knowledge graph integration."""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

from sage.config.settings import Settings
from sage.core.container import Container
from sage.core.health import HealthStatus
from sage.core.module import BaseModule
from sage.db.connection import Database
from sage.db.repository import BaseRepository
from sage.events.bus import EventBus
from sage.events.events import Event, KnowledgeEvents
from sage.knowledge.graph.interfaces import KnowledgeGraph
from sage.knowledge.graph.store import SQLiteKnowledgeGraph
from sage.knowledge.interfaces import KnowledgeManager
from sage.knowledge.models import DocumentRef, DocumentStatus, KnowledgeChunk, KnowledgeHit
from sage.logging import get_logger
from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso

log = get_logger(__name__)

_CATEGORY_HINTS: dict[str, tuple[str, ...]] = {
    "agriculture": ("crop", "soil", "farm", "harvest", "irrigation", "livestock"),
    "finance": ("budget", "invoice", "revenue", "profit", "investment", "cashflow"),
    "accounting": ("ledger", "debit", "credit", "balance sheet", "journal entry"),
    "business": ("strategy", "market", "customer", "sales", "operations"),
    "marketing": ("campaign", "brand", "seo", "audience", "advertising"),
    "programming": ("function", "class", "api", "python", "code", "bug", "repository"),
    "engineering": ("design", "system", "architecture", "prototype", "specification"),
    "personal": ("diary", "note", "todo", "journal", "reminder"),
}


class SQLiteKnowledgeManager(BaseRepository):
    def __init__(
        self,
        db: Database,
        events: EventBus,
        settings: Settings,
        graph: KnowledgeGraph | None = None,
    ) -> None:
        super().__init__(db)
        self._events = events
        self._settings = settings
        self._graph = graph

    def bind_graph(self, graph: KnowledgeGraph) -> None:
        self._graph = graph

    async def ingest(self, path: Path | str, *, category: str | None = None) -> DocumentRef:
        p = Path(path).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(f"Cannot ingest missing file: {p}")

        raw = p.read_bytes()
        checksum = hashlib.sha256(raw).hexdigest()

        existing = await self.db.fetchone(
            "SELECT id FROM knowledge_documents WHERE checksum = ? AND deleted_at IS NULL",
            (checksum,),
        )
        if existing:
            doc = await self.get(existing["id"])
            if doc:
                log.info("knowledge.duplicate", path=str(p), id=doc.id)
                return doc

        text = self._extract_text(p, raw)
        media_type = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
        title = p.stem

        doc = DocumentRef(
            path=str(p),
            title=title,
            media_type=media_type,
            category=category,
            checksum=checksum,
            size_bytes=len(raw),
            status=DocumentStatus.READY,
            summary=self._make_summary(text),
            metadata={"chars": len(text)},
        )
        if not doc.category:
            cats = self._guess_categories(text)
            doc.category = cats[0] if cats else "uncategorized"

        await self.db.execute(
            """
            INSERT INTO knowledge_documents (
                id, path, title, media_type, category, checksum, size_bytes,
                status, summary, metadata, ingested_at, deleted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                doc.id,
                doc.path,
                doc.title,
                doc.media_type,
                doc.category,
                doc.checksum,
                doc.size_bytes,
                doc.status.value,
                doc.summary,
                self.dumps(doc.metadata),
                doc.ingested_at,
            ),
        )

        chunks = self._chunk_text(doc.id, text)
        for ch in chunks:
            await self.db.execute(
                """
                INSERT INTO knowledge_chunks (id, document_id, chunk_index, content, metadata)
                VALUES (?, ?, ?, ?, ?)
                """,
                (ch.id, ch.document_id, ch.chunk_index, ch.content, self.dumps(ch.metadata)),
            )

        # Knowledge graph extraction from full text + per-chunk mentions
        graph_stats = {"entities": 0, "edges": 0}
        if self._graph is not None:
            try:
                extraction = await self._graph.extract_and_merge(
                    text,
                    source="document",
                    source_ref=doc.id,
                    document_id=doc.id,
                )
                graph_stats = {
                    "entities": len(extraction.entities),
                    "edges": len(extraction.edges),
                }
                # Link document title entity
                if doc.title:
                    await self._graph.extract_and_merge(
                        f"{doc.title} is a document about {doc.category or 'knowledge'}",
                        source="document_meta",
                        source_ref=doc.id,
                        document_id=doc.id,
                    )
            except Exception:
                log.exception("knowledge.graph_extract_failed", doc=doc.id)

        await self._events.publish(
            Event(
                type=KnowledgeEvents.INGESTED,
                payload={
                    "id": doc.id,
                    "path": doc.path,
                    "category": doc.category,
                    "chunks": len(chunks),
                    "graph": graph_stats,
                },
                source="knowledge",
            )
        )
        log.info(
            "knowledge.ingested",
            id=doc.id,
            path=str(p),
            chunks=len(chunks),
            graph_entities=graph_stats["entities"],
            graph_edges=graph_stats["edges"],
        )
        return doc

    async def search(self, query: str, *, limit: int = 10) -> list[KnowledgeHit]:
        q = f"%{query.strip()}%"
        rows = await self.db.fetchall(
            """
            SELECT c.id AS chunk_id, c.content, c.document_id,
                   d.title, d.category, d.path
            FROM knowledge_chunks c
            JOIN knowledge_documents d ON d.id = c.document_id
            WHERE d.deleted_at IS NULL
              AND (c.content LIKE ? OR IFNULL(d.title, '') LIKE ? OR IFNULL(d.summary, '') LIKE ?)
            LIMIT ?
            """,
            (q, q, q, limit),
        )
        hits: list[KnowledgeHit] = []
        for row in rows:
            snippet = row["content"][:280]
            hits.append(
                KnowledgeHit(
                    document_id=row["document_id"],
                    chunk_id=row["chunk_id"],
                    title=row["title"],
                    snippet=snippet,
                    score=1.0,
                    category=row["category"],
                    path=row["path"],
                )
            )
        return hits

    async def summarize(self, document_id: str) -> str:
        row = await self.db.fetchone(
            "SELECT summary, title FROM knowledge_documents WHERE id = ? AND deleted_at IS NULL",
            (document_id,),
        )
        if row is None:
            raise KeyError(f"Document not found: {document_id}")
        return row["summary"] or row["title"] or ""

    async def categorize(self, document_id: str) -> list[str]:
        row = await self.db.fetchone(
            "SELECT summary, category FROM knowledge_documents WHERE id = ? AND deleted_at IS NULL",
            (document_id,),
        )
        if row is None:
            raise KeyError(document_id)
        cats = self._guess_categories(row["summary"] or "")
        if row["category"] and row["category"] not in cats:
            cats.insert(0, row["category"])
        return cats or ["uncategorized"]

    async def relate(self, source_id: str, target_id: str, relation: str) -> None:
        rid = new_id("relation")
        await self.db.execute(
            """
            INSERT INTO knowledge_relations (id, source_id, target_id, relation, weight, metadata, created_at)
            VALUES (?, ?, ?, ?, 1.0, '{}', ?)
            """,
            (rid, source_id, target_id, relation, utcnow_iso()),
        )
        # Mirror into knowledge graph when ids look like entity ids or names
        if self._graph is not None:
            try:
                await self._graph.link(source_id, relation, target_id, confidence=0.7, provenance="manual")
            except Exception:
                log.debug("knowledge.graph_mirror_skipped", source=source_id, target=target_id)
        await self._events.publish(
            Event(
                type=KnowledgeEvents.RELATED,
                payload={"id": rid, "source": source_id, "target": target_id, "relation": relation},
                source="knowledge",
            )
        )

    async def get(self, document_id: str) -> DocumentRef | None:
        row = await self.db.fetchone(
            "SELECT * FROM knowledge_documents WHERE id = ? AND deleted_at IS NULL",
            (document_id,),
        )
        if row is None:
            return None
        return DocumentRef(
            id=row["id"],
            path=row["path"],
            title=row["title"],
            media_type=row["media_type"],
            category=row["category"],
            checksum=row["checksum"],
            size_bytes=row["size_bytes"],
            status=DocumentStatus(row["status"]),
            summary=row["summary"],
            metadata=self.loads(row["metadata"], {}),
            ingested_at=row["ingested_at"],
        )

    async def count_documents(self) -> int:
        val = await self.db.scalar(
            "SELECT COUNT(*) FROM knowledge_documents WHERE deleted_at IS NULL"
        )
        return int(val or 0)

    def _extract_text(self, path: Path, raw: bytes) -> str:
        ext = path.suffix.lower()
        if ext in {".txt", ".md", ".csv", ".py", ".json", ".yaml", ".yml", ".toml", ".log"}:
            return raw.decode("utf-8", errors="replace")
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return (
                f"[Binary document: {path.name} ({ext or 'unknown'})]. "
                "Install sage[documents] parsers for full extraction in a later milestone."
            )

    def _chunk_text(self, document_id: str, text: str, size: int = 800, overlap: int = 100) -> list[KnowledgeChunk]:
        text = text.strip()
        if not text:
            return [
                KnowledgeChunk(document_id=document_id, chunk_index=0, content="(empty document)")
            ]
        chunks: list[KnowledgeChunk] = []
        i = 0
        idx = 0
        while i < len(text):
            piece = text[i : i + size]
            chunks.append(
                KnowledgeChunk(document_id=document_id, chunk_index=idx, content=piece)
            )
            idx += 1
            i += max(size - overlap, 1)
        return chunks

    def _make_summary(self, text: str, max_len: int = 400) -> str:
        cleaned = " ".join(text.split())
        if len(cleaned) <= max_len:
            return cleaned
        return cleaned[: max_len - 3] + "..."

    def _guess_categories(self, text: str) -> list[str]:
        lower = text.lower()
        scores: list[tuple[int, str]] = []
        for cat, keywords in _CATEGORY_HINTS.items():
            score = sum(1 for kw in keywords if kw in lower)
            if score:
                scores.append((score, cat))
        scores.sort(reverse=True)
        return [c for _, c in scores[:3]]


class KnowledgeModule(BaseModule):
    name = "knowledge"
    version = "0.3.1"
    is_critical = False

    def __init__(self, container: Container) -> None:
        super().__init__(container)
        self._mgr: SQLiteKnowledgeManager | None = None
        self._graph: SQLiteKnowledgeGraph | None = None

    async def _on_initialize(self) -> None:
        db = self.container.resolve(Database)
        events = self.container.resolve(EventBus)
        settings = self.container.resolve(Settings)
        self._graph = SQLiteKnowledgeGraph(db, events)
        self._mgr = SQLiteKnowledgeManager(db, events, settings, graph=self._graph)
        self.container.register_instance(KnowledgeGraph, self._graph)
        self.container.register_instance(SQLiteKnowledgeGraph, self._graph)
        self.container.register_instance(KnowledgeManager, self._mgr)
        self.container.register_instance(SQLiteKnowledgeManager, self._mgr)

        # Seed a small core ontology
        await self._seed_core_ontology()

    async def _seed_core_ontology(self) -> None:
        assert self._graph is not None
        from sage.knowledge.graph.business_seed import BUSINESS_SEED_ONTOLOGY

        seed_text = """
        Tomato is a crop. Tomato requires water. Tomato requires soil.
        Tomato grows in warm climate. Tomato is affected by blight.
        Tomato harvested after 90 days. Irrigation is used for water.
        Basil is a crop. Basil requires water. Greenhouse is a place.
        Budget is a metric. Revenue is a metric. SAGE is a concept.
        Orchestrator is a concept. Memory is a concept.
        """
        try:
            await self._graph.extract_and_merge(seed_text, source="seed_ontology", source_ref="boot")
            await self._graph.extract_and_merge(
                BUSINESS_SEED_ONTOLOGY,
                source="business_seed_ontology",
                source_ref="boot_v031",
            )
        except Exception:
            log.exception("knowledge.seed_failed")

    async def _on_health(self) -> HealthStatus | None:
        if self._mgr is None or self._graph is None:
            return HealthStatus.unhealthy(self.name, "not initialized")
        n = await self._mgr.count_documents()
        stats = await self._graph.stats()
        return HealthStatus.healthy(
            self.name,
            "ok",
            documents=n,
            kg_entities=stats.get("entities", 0),
            kg_edges=stats.get("edges", 0),
        )

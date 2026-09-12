"""
Layered retrieval pipeline:

1. Memory search
2. Knowledge graph lookup
3. Document retrieval
4. Semantic search (embedding stub when available)
5. Context ranking
6. Confidence scoring
"""

from __future__ import annotations

from typing import Any

from sage.logging import get_logger
from sage.retrieval.citations import build_citations
from sage.retrieval.models import EvidenceItem, RetrievalLayer, RetrievalResult

log = get_logger(__name__)


class LayeredRetriever:
    def __init__(self, container: Any) -> None:
        self._container = container

    async def retrieve(self, query: str, *, limit: int = 10) -> RetrievalResult:
        items: list[EvidenceItem] = []
        explanation: list[str] = []

        mem_items = await self._layer_memory(query, limit=limit)
        items.extend(mem_items)
        explanation.append(f"Memory layer: {len(mem_items)} hit(s)")

        graph_items = await self._layer_graph(query, limit=limit)
        items.extend(graph_items)
        explanation.append(f"Knowledge graph layer: {len(graph_items)} fact(s)")

        doc_items = await self._layer_documents(query, limit=limit)
        items.extend(doc_items)
        explanation.append(f"Document layer: {len(doc_items)} hit(s)")

        sem_items = await self._layer_semantic(query, limit=max(3, limit // 2))
        items.extend(sem_items)
        if sem_items:
            explanation.append(f"Semantic layer: {len(sem_items)} hit(s)")

        pattern_items = await self._layer_patterns(query, limit=3)
        items.extend(pattern_items)
        if pattern_items:
            explanation.append(f"Pattern layer: {len(pattern_items)} hit(s)")

        ranked = self._rank(items, query)[:limit]
        overall = self._overall_confidence(ranked)

        memories = [i.content for i in ranked if i.layer == RetrievalLayer.MEMORY]
        graph_facts = [i.content for i in ranked if i.layer == RetrievalLayer.KNOWLEDGE_GRAPH]
        documents = [i.content for i in ranked if i.layer == RetrievalLayer.DOCUMENT]

        explanation.append(f"Ranked top {len(ranked)}; overall confidence={overall:.2f}")

        result = RetrievalResult(
            query=query,
            items=items,
            ranked=ranked,
            citations=build_citations(ranked),
            memories=memories,
            graph_facts=graph_facts,
            documents=documents,
            overall_confidence=overall,
            explanation=explanation,
        )
        log.debug(
            "retrieval.complete",
            query=query[:80],
            total=len(items),
            ranked=len(ranked),
            confidence=overall,
        )
        return result

    async def _layer_memory(self, query: str, *, limit: int) -> list[EvidenceItem]:
        from sage.memory.interfaces import MemorySystem

        mem = self._container.try_resolve(MemorySystem)
        if not mem:
            return []
        try:
            found = await mem.recall(query, limit=limit)
        except Exception:
            log.exception("retrieval.memory_failed")
            return []
        return [
            EvidenceItem(
                layer=RetrievalLayer.MEMORY,
                content=m.content,
                score=float(m.importance),
                confidence=float(m.confidence),
                source_ref=m.id,
                metadata={"type": m.type.value, "importance": m.importance},
            )
            for m in found
        ]

    async def _layer_graph(self, query: str, *, limit: int) -> list[EvidenceItem]:
        from sage.knowledge.graph.interfaces import KnowledgeGraph

        kg = self._container.try_resolve(KnowledgeGraph)
        if not kg:
            return []
        try:
            entities = await kg.search_entities(query, limit=min(10, limit))
            items: list[EvidenceItem] = []
            for ent in entities:
                triples = await kg.neighbors(ent.id, direction="both", limit=5)
                if not triples:
                    items.append(
                        EvidenceItem(
                            layer=RetrievalLayer.KNOWLEDGE_GRAPH,
                            content=f"{ent.name} ({ent.entity_type.value})",
                            score=float(ent.confidence),
                            confidence=float(ent.confidence),
                            source_ref=ent.id,
                            metadata={"entity_type": ent.entity_type.value},
                        )
                    )
                for t in triples:
                    fact = f"{t.subject.name} —{t.relation}→ {t.object.name}"
                    items.append(
                        EvidenceItem(
                            layer=RetrievalLayer.KNOWLEDGE_GRAPH,
                            content=fact,
                            score=float(t.confidence) * 1.1,  # slight boost for structured facts
                            confidence=float(t.confidence),
                            source_ref=t.edge.id,
                            metadata={
                                "subject": t.subject.name,
                                "relation": t.relation,
                                "object": t.object.name,
                            },
                        )
                    )
            # Also try SPO query on tokens
            tokens = [t for t in query.split() if len(t) > 2][:4]
            for tok in tokens:
                for t in await kg.query_relation(subject=tok, limit=5):
                    fact = f"{t.subject.name} —{t.relation}→ {t.object.name}"
                    items.append(
                        EvidenceItem(
                            layer=RetrievalLayer.KNOWLEDGE_GRAPH,
                            content=fact,
                            score=float(t.confidence),
                            confidence=float(t.confidence),
                            source_ref=t.edge.id,
                        )
                    )
            # Dedupe by content
            seen: set[str] = set()
            unique: list[EvidenceItem] = []
            for it in items:
                if it.content in seen:
                    continue
                seen.add(it.content)
                unique.append(it)
            return unique[: limit * 2]
        except Exception:
            log.exception("retrieval.graph_failed")
            return []

    async def _layer_documents(self, query: str, *, limit: int) -> list[EvidenceItem]:
        from sage.knowledge.interfaces import KnowledgeManager

        km = self._container.try_resolve(KnowledgeManager)
        if not km:
            return []
        try:
            hits = await km.search(query, limit=limit)
        except Exception:
            log.exception("retrieval.documents_failed")
            return []
        return [
            EvidenceItem(
                layer=RetrievalLayer.DOCUMENT,
                content=f"{h.title}: {h.snippet}" if h.title else h.snippet,
                score=float(h.score),
                confidence=min(0.9, 0.4 + float(h.score) * 0.3),
                source_ref=h.document_id,
                metadata={"category": h.category, "path": h.path},
            )
            for h in hits
        ]

    async def _layer_semantic(self, query: str, *, limit: int) -> list[EvidenceItem]:
        """Use embedding model to score memory texts when available (stub ok)."""
        from sage.memory.interfaces import MemorySystem
        from sage.models.interfaces import ModelRouter

        router = self._container.try_resolve(ModelRouter)
        mem = self._container.try_resolve(MemorySystem)
        if not router or not mem:
            return []
        try:
            recent = await mem.recall("", limit=30)
            if not recent:
                return []
            emb = router.get_embedding_model()
            texts = [query] + [m.content for m in recent]
            vectors = await emb.embed(texts)
            if not vectors or len(vectors) < 2:
                return []
            qv = vectors[0]

            def cos(a: list[float], b: list[float]) -> float:
                dot = sum(x * y for x, y in zip(a, b, strict=False))
                na = sum(x * x for x in a) ** 0.5 or 1.0
                nb = sum(x * x for x in b) ** 0.5 or 1.0
                return dot / (na * nb)

            scored: list[tuple[float, Any]] = []
            for m, vec in zip(recent, vectors[1:], strict=False):
                scored.append((cos(qv, vec), m))
            scored.sort(key=lambda x: x[0], reverse=True)
            items: list[EvidenceItem] = []
            for score, m in scored[:limit]:
                if score < 0.15:
                    continue
                items.append(
                    EvidenceItem(
                        layer=RetrievalLayer.SEMANTIC,
                        content=m.content,
                        score=float(score),
                        confidence=min(0.85, float(score)),
                        source_ref=m.id,
                        metadata={"similarity": score},
                    )
                )
            return items
        except Exception:
            log.exception("retrieval.semantic_failed")
            return []

    async def _layer_patterns(self, query: str, *, limit: int) -> list[EvidenceItem]:
        from sage.learning.interfaces import LearningEngine

        learn = self._container.try_resolve(LearningEngine)
        if not learn:
            return []
        find = getattr(learn, "find_patterns", None)
        if not callable(find):
            return []
        try:
            patterns = await find(query, limit=limit)
        except Exception:
            return []
        return [
            EvidenceItem(
                layer=RetrievalLayer.PATTERN,
                content=p.get("description", str(p)),
                score=float(p.get("confidence", 0.3)),
                confidence=float(p.get("confidence", 0.3)),
                source_ref=p.get("id"),
                metadata=p,
            )
            for p in patterns
        ]

    def _rank(self, items: list[EvidenceItem], query: str) -> list[EvidenceItem]:
        q_tokens = {t.lower() for t in query.split() if len(t) > 2}
        layer_boost = {
            RetrievalLayer.KNOWLEDGE_GRAPH: 0.15,
            RetrievalLayer.MEMORY: 0.1,
            RetrievalLayer.DOCUMENT: 0.05,
            RetrievalLayer.SEMANTIC: 0.08,
            RetrievalLayer.PATTERN: 0.05,
        }

        def key(item: EvidenceItem) -> float:
            overlap = 0.0
            if q_tokens:
                content_tokens = {t.lower() for t in item.content.split()}
                overlap = len(q_tokens & content_tokens) / max(len(q_tokens), 1)
            return (
                item.score * 0.45
                + item.confidence * 0.35
                + overlap * 0.15
                + layer_boost.get(item.layer, 0.0)
            )

        # Dedupe near-identical content keeping highest score
        best: dict[str, EvidenceItem] = {}
        for item in items:
            norm = " ".join(item.content.lower().split())[:200]
            prev = best.get(norm)
            if prev is None or key(item) > key(prev):
                best[norm] = item
        return sorted(best.values(), key=key, reverse=True)

    def _overall_confidence(self, ranked: list[EvidenceItem]) -> float:
        if not ranked:
            return 0.0
        # Weighted mean with diminishing returns for volume
        weights = [1.0 / (i + 1) for i in range(len(ranked))]
        total_w = sum(weights) or 1.0
        mean = sum(r.confidence * w for r, w in zip(ranked, weights, strict=False)) / total_w
        volume_boost = min(0.1, len(ranked) * 0.015)
        layers = {r.layer for r in ranked}
        multi_layer = 0.08 if len(layers) >= 2 else 0.0
        return round(min(0.95, mean + volume_boost + multi_layer), 3)

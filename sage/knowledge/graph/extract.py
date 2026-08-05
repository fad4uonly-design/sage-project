"""
Rule-based entity & relation extraction.

Deterministic offline extractor — LLM enrichment can plug in later via the same
ExtractionResult contract. Tuned for agriculture/business/general English prose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sage.knowledge.graph.business_seed import BUSINESS_SEED_TYPES
from sage.knowledge.graph.models import Entity, EntityType, RelationType, canonicalize
from sage.utils.ids import new_id

# Seed ontology: common domain entities → type
_SEED_TYPES: dict[str, EntityType] = {
    "tomato": EntityType.CROP,
    "tomatoes": EntityType.CROP,
    "basil": EntityType.CROP,
    "wheat": EntityType.CROP,
    "corn": EntityType.CROP,
    "rice": EntityType.CROP,
    "lettuce": EntityType.CROP,
    "herb": EntityType.CROP,
    "crop": EntityType.CROP,
    "crops": EntityType.CROP,
    "water": EntityType.RESOURCE,
    "irrigation": EntityType.PROCESS,
    "soil": EntityType.RESOURCE,
    "fertilizer": EntityType.RESOURCE,
    "blight": EntityType.CONDITION,
    "pest": EntityType.CONDITION,
    "drought": EntityType.CONDITION,
    "greenhouse": EntityType.PLACE,
    "farm": EntityType.PLACE,
    "field": EntityType.PLACE,
    "budget": EntityType.METRIC,
    "revenue": EntityType.REVENUE,
    "profit": EntityType.METRIC,
    "invoice": EntityType.CONCEPT,
    "python": EntityType.TOOL,
    "api": EntityType.TOOL,
    "database": EntityType.TOOL,
    "sage": EntityType.CONCEPT,
    "memory": EntityType.CONCEPT,
    "orchestrator": EntityType.CONCEPT,
    **BUSINESS_SEED_TYPES,
}

# Pattern → (relation, subject_group, object_group)  — groups are 1-indexed
_RELATION_PATTERNS: list[tuple[re.Pattern[str], str, int, int]] = [
    (
        re.compile(
            r"\b([A-Za-z][\w\s\-]{1,40}?)\s+(?:is an?|are)\s+([A-Za-z][\w\s\-]{1,40})\b",
            re.I,
        ),
        RelationType.IS_A.value,
        1,
        2,
    ),
    (
        re.compile(
            r"\b([A-Za-z][\w\s\-]{1,40}?)\s+requires?\s+([A-Za-z][\w\s\-]{1,40})\b",
            re.I,
        ),
        RelationType.REQUIRES.value,
        1,
        2,
    ),
    (
        re.compile(
            r"\b([A-Za-z][\w\s\-]{1,40}?)\s+needs?\s+([A-Za-z][\w\s\-]{1,40})\b",
            re.I,
        ),
        RelationType.REQUIRES.value,
        1,
        2,
    ),
    (
        re.compile(
            r"\b([A-Za-z][\w\s\-]{1,40}?)\s+grows?\s+in\s+([A-Za-z][\w\s\-]{1,40})\b",
            re.I,
        ),
        RelationType.GROWS_IN.value,
        1,
        2,
    ),
    (
        re.compile(
            r"\b([A-Za-z][\w\s\-]{1,40}?)\s+(?:is\s+)?affected by\s+([A-Za-z][\w\s\-]{1,40})\b",
            re.I,
        ),
        RelationType.AFFECTED_BY.value,
        1,
        2,
    ),
    (
        re.compile(
            r"\b([A-Za-z][\w\s\-]{1,40}?)\s+causes?\s+([A-Za-z][\w\s\-]{1,40})\b",
            re.I,
        ),
        RelationType.CAUSES.value,
        1,
        2,
    ),
    (
        re.compile(
            r"\b([A-Za-z][\w\s\-]{1,40}?)\s+(?:is\s+)?used for\s+([A-Za-z][\w\s\-]{1,40})\b",
            re.I,
        ),
        RelationType.USED_FOR.value,
        1,
        2,
    ),
    (
        re.compile(
            r"\b([A-Za-z][\w\s\-]{1,40}?)\s+depends on\s+([A-Za-z][\w\s\-]{1,40})\b",
            re.I,
        ),
        RelationType.DEPENDS_ON.value,
        1,
        2,
    ),
    (
        re.compile(
            r"\b([A-Za-z][\w\s\-]{1,40}?)\s+(?:is\s+)?part of\s+([A-Za-z][\w\s\-]{1,40})\b",
            re.I,
        ),
        RelationType.PART_OF.value,
        1,
        2,
    ),
    (
        re.compile(
            r"\b([A-Za-z][\w\s\-]{1,40}?)\s+produces?\s+([A-Za-z][\w\s\-]{1,40})\b",
            re.I,
        ),
        RelationType.PRODUCES.value,
        1,
        2,
    ),
    (
        re.compile(
            r"\b([A-Za-z][\w\s\-]{1,40}?)\s+harvested after\s+(\d+\s*(?:days?|weeks?|months?))",
            re.I,
        ),
        RelationType.HARVESTED_AFTER.value,
        1,
        2,
    ),
    (
        re.compile(
            r"\b([A-Za-z][\w\s\-]{1,40}?)\s+(?:is\s+)?located in\s+([A-Za-z][\w\s\-]{1,40})\b",
            re.I,
        ),
        RelationType.LOCATED_IN.value,
        1,
        2,
    ),
    # Business patterns (v0.3.1)
    (
        re.compile(
            r"\b([A-Za-z][\w\s\-]{1,40}?)\s+sells?\s+to\s+([A-Za-z][\w\s\-]{1,40})\b",
            re.I,
        ),
        RelationType.SELLS_TO.value,
        1,
        2,
    ),
    (
        re.compile(
            r"\b([A-Za-z][\w\s\-]{1,40}?)\s+buys?\s+from\s+([A-Za-z][\w\s\-]{1,40})\b",
            re.I,
        ),
        RelationType.BUYS_FROM.value,
        1,
        2,
    ),
    (
        re.compile(
            r"\b([A-Za-z][\w\s\-]{1,40}?)\s+employs?\s+([A-Za-z][\w\s\-]{1,40})\b",
            re.I,
        ),
        RelationType.EMPLOYS.value,
        1,
        2,
    ),
    (
        re.compile(
            r"\b([A-Za-z][\w\s\-]{1,40}?)\s+competes?\s+with\s+([A-Za-z][\w\s\-]{1,40})\b",
            re.I,
        ),
        RelationType.COMPETES_WITH.value,
        1,
        2,
    ),
    (
        re.compile(
            r"\b([A-Za-z][\w\s\-]{1,40}?)\s+targets?\s+([A-Za-z][\w\s\-]{1,40})\b",
            re.I,
        ),
        RelationType.TARGETS.value,
        1,
        2,
    ),
    (
        re.compile(
            r"\b([A-Za-z][\w\s\-]{1,40}?)\s+generates?\s+([A-Za-z][\w\s\-]{1,40})\b",
            re.I,
        ),
        RelationType.GENERATES.value,
        1,
        2,
    ),
    (
        re.compile(
            r"\b([A-Za-z][\w\s\-]{1,40}?)\s+incurs?\s+([A-Za-z][\w\s\-]{1,40})\b",
            re.I,
        ),
        RelationType.INCURS.value,
        1,
        2,
    ),
    (
        re.compile(
            r"\b([A-Za-z][\w\s\-]{1,40}?)\s+measures?\s+([A-Za-z][\w\s\-]{1,40})\b",
            re.I,
        ),
        RelationType.MEASURES.value,
        1,
        2,
    ),
    (
        re.compile(
            r"\b([A-Za-z][\w\s\-]{1,40}?)\s+(?:is\s+)?owned by\s+([A-Za-z][\w\s\-]{1,40})\b",
            re.I,
        ),
        RelationType.OWNED_BY.value,
        1,
        2,
    ),
    (
        re.compile(
            r"\b([A-Za-z][\w\s\-]{1,40}?)\s+manages?\s+([A-Za-z][\w\s\-]{1,40})\b",
            re.I,
        ),
        RelationType.MANAGES.value,
        1,
        2,
    ),
]

_CAPITALIZED = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b")
_STOP_ENTITIES = frozenset(
    {
        "the",
        "a",
        "an",
        "this",
        "that",
        "these",
        "those",
        "it",
        "they",
        "we",
        "you",
        "i",
        "and",
        "or",
        "but",
        "if",
        "when",
        "where",
        "what",
        "which",
        "who",
        "how",
        "for",
        "with",
        "from",
        "into",
        "about",
        "after",
        "before",
        "between",
        "under",
        "over",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "shall",
        "can",
        "not",
        "no",
        "yes",
        "all",
        "each",
        "every",
        "both",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "just",
        "also",
    }
)


@dataclass
class RawExtraction:
    entities: dict[str, Entity] = field(default_factory=dict)  # canonical → Entity
    triples: list[tuple[str, str, str, float]] = field(default_factory=list)
    # (src_canonical, relation, tgt_canonical, confidence)


class TextExtractor:
    """Extract entities and relations from free text."""

    def extract(self, text: str, *, source: str = "extraction") -> RawExtraction:
        result = RawExtraction()
        if not text or not text.strip():
            return result

        # 1) Relation patterns first (they introduce entities)
        for pattern, relation, sg, og in _RELATION_PATTERNS:
            for m in pattern.finditer(text):
                subj = self._clean_span(m.group(sg))
                obj = self._clean_span(m.group(og))
                if not subj or not obj:
                    continue
                self._ensure_entity(result, subj, source=source)
                self._ensure_entity(result, obj, source=source)
                src_c, tgt_c = canonicalize(subj), canonicalize(obj)
                if src_c == tgt_c:
                    continue  # skip tautological self-edges
                result.triples.append((src_c, relation, tgt_c, 0.75))


        # 2) Seed lexicon hits
        lower = text.lower()
        for term, etype in _SEED_TYPES.items():
            if re.search(rf"\b{re.escape(term)}\b", lower):
                display = term.title() if etype == EntityType.CROP else term
                # Prefer singular crop names
                name = term.rstrip("s") if etype == EntityType.CROP and term.endswith("s") else term
                ent = self._ensure_entity(result, name, source=source, entity_type=etype)
                if display and ent.name.lower() == name.lower():
                    ent.name = name.title() if len(name) > 2 else name

        # 3) Capitalized multi-word phrases (proper nouns)
        for m in _CAPITALIZED.finditer(text):
            span = m.group(1).strip()
            if span.lower() in _STOP_ENTITIES or len(span) < 3:
                continue
            # Skip sentence starters that are common words if alone
            if " " not in span and span.lower() in _SEED_TYPES:
                continue
            self._ensure_entity(result, span, source=source)

        # 4) Co-occurrence related_to among seed entities in same sentence
        sentences = re.split(r"[.!?\n]+", text)
        for sent in sentences:
            found: list[str] = []
            sl = sent.lower()
            for term in _SEED_TYPES:
                if re.search(rf"\b{re.escape(term)}\b", sl):
                    name = term.rstrip("s") if term.endswith("s") and _SEED_TYPES[term] == EntityType.CROP else term
                    can = canonicalize(name)
                    if can in result.entities:
                        found.append(can)
            for i, a in enumerate(found):
                for b in found[i + 1 :]:
                    if a != b:
                        result.triples.append((a, RelationType.RELATED_TO.value, b, 0.4))

        return result

    def _clean_span(self, span: str) -> str:
        s = span.strip().strip(".,;:\"'()[]")
        s = re.sub(r"\s+", " ", s)
        if not s or s.lower() in _STOP_ENTITIES:
            return ""
        if len(s) > 60:
            s = s[:60].rsplit(" ", 1)[0]
        return s

    def _ensure_entity(
        self,
        result: RawExtraction,
        name: str,
        *,
        source: str,
        entity_type: EntityType | None = None,
    ) -> Entity:
        can = canonicalize(name)
        if not can:
            # fallback
            can = name.lower().strip()
        if can in result.entities:
            ent = result.entities[can]
            if entity_type and ent.entity_type == EntityType.CONCEPT:
                ent.entity_type = entity_type
            return ent
        et = entity_type or _SEED_TYPES.get(can) or _SEED_TYPES.get(name.lower()) or EntityType.CONCEPT
        # singular crops
        if et == EntityType.UNKNOWN:
            et = EntityType.CONCEPT
        ent = Entity(
            id=new_id("ent"),
            name=name.strip(),
            canonical_name=can,
            entity_type=et,
            confidence=0.6 if entity_type or can in {canonicalize(k) for k in _SEED_TYPES} else 0.45,
            source=source,
        )
        result.entities[can] = ent
        return ent

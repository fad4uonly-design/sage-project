"""Knowledge graph domain models."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso


class EntityType(str, Enum):
    # Core / general
    CONCEPT = "concept"
    PERSON = "person"
    PLACE = "place"
    ORGANIZATION = "organization"
    CROP = "crop"
    PRODUCT = "product"
    PROCESS = "process"
    EVENT = "event"
    DOCUMENT = "document"
    TOOL = "tool"
    METRIC = "metric"
    CONDITION = "condition"
    RESOURCE = "resource"
    UNKNOWN = "unknown"
    # Business Intelligence (v0.3.1)
    COMPANY = "company"
    CUSTOMER = "customer"
    SUPPLIER = "supplier"
    SERVICE = "service"
    EMPLOYEE = "employee"
    DEPARTMENT = "department"
    MARKET = "market"
    COMPETITOR = "competitor"
    CAMPAIGN = "campaign"
    REVENUE = "revenue"
    EXPENSE = "expense"
    ASSET = "asset"
    LIABILITY = "liability"
    KPI = "kpi"
    PROJECT = "project"
    GOAL = "goal"
    RISK = "risk"
    OPPORTUNITY = "opportunity"


class RelationType(str, Enum):
    IS_A = "is_a"
    PART_OF = "part_of"
    REQUIRES = "requires"
    PRODUCES = "produces"
    AFFECTED_BY = "affected_by"
    GROWS_IN = "grows_in"
    LOCATED_IN = "located_in"
    OWNED_BY = "owned_by"
    RELATED_TO = "related_to"
    CAUSES = "causes"
    PREVENTS = "prevents"
    USED_FOR = "used_for"
    DEPENDS_ON = "depends_on"
    SIMILAR_TO = "similar_to"
    OPPOSITE_OF = "opposite_of"
    HAS_PROPERTY = "has_property"
    OCCURS_AFTER = "occurs_after"
    HARVESTED_AFTER = "harvested_after"
    MENTIONS = "mentions"
    DERIVED_FROM = "derived_from"
    CUSTOM = "custom"
    # Business relations (v0.3.1)
    SELLS_TO = "sells_to"
    BUYS_FROM = "buys_from"
    EMPLOYS = "employs"
    REPORTS_TO = "reports_to"
    COMPETES_WITH = "competes_with"
    TARGETS = "targets"
    MEASURES = "measures"
    FUNDS = "funds"
    MANAGES = "manages"
    BELONGS_TO = "belongs_to"
    GENERATES = "generates"
    INCURS = "incurs"
    MITIGATES = "mitigates"
    SERVES = "serves"


_BIDIRECTIONAL_DEFAULTS: frozenset[str] = frozenset(
    {
        RelationType.RELATED_TO.value,
        RelationType.SIMILAR_TO.value,
        RelationType.OPPOSITE_OF.value,
        RelationType.COMPETES_WITH.value,
    }
)


class Entity(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ent"))
    name: str
    canonical_name: str = ""
    entity_type: EntityType = EntityType.CONCEPT
    description: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source: str | None = None
    source_ref: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    version: int = 1
    created_at: str = Field(default_factory=utcnow_iso)
    updated_at: str = Field(default_factory=utcnow_iso)
    deleted_at: str | None = None

    def model_post_init(self, __context: Any) -> None:
        if not self.canonical_name:
            object.__setattr__(self, "canonical_name", canonicalize(self.name))


class GraphEdge(BaseModel):
    id: str = Field(default_factory=lambda: new_id("edge"))
    source_id: str
    target_id: str
    relation: str
    weight: float = Field(default=1.0, ge=0.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    bidirectional: bool = False
    source: str | None = None
    source_ref: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    version: int = 1
    created_at: str = Field(default_factory=utcnow_iso)
    updated_at: str = Field(default_factory=utcnow_iso)
    deleted_at: str | None = None

    def model_post_init(self, __context: Any) -> None:
        if not self.bidirectional and self.relation in _BIDIRECTIONAL_DEFAULTS:
            object.__setattr__(self, "bidirectional", True)


class GraphTriple(BaseModel):
    """Human-readable (subject, predicate, object) with provenance."""

    subject: Entity
    relation: str
    object: Entity
    edge: GraphEdge
    confidence: float = 0.5


class GraphPath(BaseModel):
    nodes: list[Entity] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    score: float = 0.0


class ExtractionResult(BaseModel):
    entities: list[Entity] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    mentions: int = 0
    source_ref: str | None = None


def canonicalize(name: str) -> str:
    """Normalize entity names for dedup: lowercase, collapse whitespace, strip punctuation edges."""
    import re

    s = name.strip().lower()
    s = re.sub(r"[^\w\s\-/&]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

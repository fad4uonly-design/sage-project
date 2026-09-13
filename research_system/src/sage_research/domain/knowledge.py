"""Knowledge records (Layers 1–3) and their supporting vocabulary.

A :class:`KnowledgeRecord` is an immutable, evidence-backed claim. Every record
carries: state, replication status, generalization state, evidence sources,
counterevidence, a dependency chain, an uncertainty profile, and an overall
confidence that is validated to never exceed the weakest dependency.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from .confidence import Confidence, UncertaintyProfile


class KnowledgeLayer(StrEnum):
    """The five knowledge layers.

    Layers 1–3 are active for Research Specimen 001. Layers 4 and 5 are dormant
    and must not be produced by this milestone.
    """

    MODEL = "model"           # Layer 1 — what the model *is* (artifact, architecture)
    MECHANISM = "mechanism"   # Layer 2 — how components produce behavior
    RESEARCH = "research"     # Layer 3 — research process knowledge (methods, lessons)
    ENGINEERING = "engineering"  # Layer 4 — DORMANT (production engineering knowledge)
    SELF = "self"             # Layer 5 — DORMANT (SAGE self-knowledge)


class KnowledgeState(StrEnum):
    CONFIRMED = "confirmed"
    REPLICATED = "replicated"
    STRONG_EVIDENCE = "strong_evidence"
    WEAK_EVIDENCE = "weak_evidence"
    HYPOTHESIS = "hypothesis"
    UNKNOWN = "unknown"
    FAILED_PREDICTION = "failed_prediction"
    CONTESTED = "contested"


class ReplicationStatus(StrEnum):
    NOT_ATTEMPTED = "not_attempted"
    SINGLE_OBSERVATION = "single_observation"
    IN_PROGRESS = "in_progress"
    REPLICATED = "replicated"
    FAILED_TO_REPLICATE = "failed_to_replicate"


class GeneralizationState(StrEnum):
    UNASSESSED = "unassessed"
    THIS_SPECIMEN = "this_specimen"
    WITHIN_FAMILY = "within_family"
    ACROSS_FAMILIES = "across_families"
    CONTRADICTED = "contradicted"


class EvidenceCategory(StrEnum):
    """Evidence categories.

    Representation, transformation, and causal contribution MUST remain
    separate evidence categories. Correlation is never automatically causation:
    a claim/edge only counts as causal when backed by causal evidence
    (e.g. ablation or activation patching).
    """

    ARCHITECTURE = "architecture"
    BEHAVIOR = "behavior"
    REPRESENTATION = "representation"
    TRANSFORMATION = "transformation"
    CAUSAL = "causal"
    CORRELATIONAL = "correlational"


class EvidenceStrength(StrEnum):
    CONFIRMED = "confirmed"
    STRONG = "strong"
    WEAK = "weak"
    ANECDOTAL = "anecdotal"


@dataclass(frozen=True)
class EvidenceRef:
    """A pointer to evidence produced by a reproducible method run."""

    source_kind: str          # e.g. "architecture_inspection"
    source_id: str            # experiment / artifact id
    category: EvidenceCategory
    strength: EvidenceStrength
    description: str
    timestamp_utc: str

    def to_dict(self) -> dict[str, str]:
        return {
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "category": self.category.value,
            "strength": self.strength.value,
            "description": self.description,
            "timestamp_utc": self.timestamp_utc,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> EvidenceRef:
        return cls(
            source_kind=data["source_kind"],
            source_id=data["source_id"],
            category=EvidenceCategory(data["category"]),
            strength=EvidenceStrength(data["strength"]),
            description=data["description"],
            timestamp_utc=data["timestamp_utc"],
        )


@dataclass(frozen=True)
class KnowledgeReference:
    """A pointer to another knowledge record (dependency chain element)."""

    knowledge_id: str
    layer: KnowledgeLayer

    def to_dict(self) -> dict[str, str]:
        return {"knowledge_id": self.knowledge_id, "layer": self.layer.value}

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> KnowledgeReference:
        return cls(knowledge_id=data["knowledge_id"], layer=KnowledgeLayer(data["layer"]))


def stable_knowledge_id(subject: str, claim: str) -> str:
    """Deterministic knowledge id derived from content (not from ordering or clock)."""
    digest = hashlib.sha256(f"{subject}\n{claim}".encode()).hexdigest()
    return f"kn-{digest[:24]}"


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


_STATES_REQUIRING_EVIDENCE = {
    KnowledgeState.CONFIRMED,
    KnowledgeState.REPLICATED,
    KnowledgeState.STRONG_EVIDENCE,
    KnowledgeState.WEAK_EVIDENCE,
}


@dataclass(frozen=True)
class KnowledgeRecord:
    """An immutable, evidence-backed knowledge claim."""

    knowledge_id: str
    layer: KnowledgeLayer
    subject: str                     # model identity slug (or research-layer subject)
    claim: str
    state: KnowledgeState
    uncertainty: UncertaintyProfile   # per-domain components + ceiling
    confidence: Confidence            # overall, must be <= ceiling
    replication: ReplicationStatus
    generalization: GeneralizationState
    evidence: tuple[EvidenceRef, ...]
    counterevidence: tuple[EvidenceRef, ...]
    dependencies: tuple[KnowledgeReference, ...]
    system_version: str
    created_utc: str
    provenance: str

    def __post_init__(self) -> None:
        if self.confidence.value > self.uncertainty.ceiling.value:
            raise ValueError(
                "confidence exceeds the weakest uncertainty domain: "
                f"{self.confidence.value} > {self.uncertainty.ceiling.value}"
            )
        if self.state in _STATES_REQUIRING_EVIDENCE and not self.evidence:
            raise ValueError(
                f"state {self.state.value!r} requires at least one evidence reference"
            )

    @property
    def confidence_ceiling(self) -> Confidence:
        """The strongest confidence this record could support (weakest domain)."""
        return self.uncertainty.ceiling

    def to_dict(self) -> dict[str, object]:
        return {
            "knowledge_id": self.knowledge_id,
            "layer": self.layer.value,
            "subject": self.subject,
            "claim": self.claim,
            "state": self.state.value,
            "uncertainty": self.uncertainty.to_dict(),
            "confidence": self.confidence.to_dict(),
            "replication": self.replication.value,
            "generalization": self.generalization.value,
            "evidence": [e.to_dict() for e in self.evidence],
            "counterevidence": [e.to_dict() for e in self.counterevidence],
            "dependencies": [d.to_dict() for d in self.dependencies],
            "system_version": self.system_version,
            "created_utc": self.created_utc,
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> KnowledgeRecord:
        return cls(
            knowledge_id=str(data["knowledge_id"]),
            layer=KnowledgeLayer(str(data["layer"])),
            subject=str(data["subject"]),
            claim=str(data["claim"]),
            state=KnowledgeState(str(data["state"])),
            uncertainty=UncertaintyProfile.from_dict(data["uncertainty"]),  # type: ignore[arg-type]
            confidence=Confidence.from_dict(data["confidence"]),  # type: ignore[arg-type]
            replication=ReplicationStatus(str(data["replication"])),
            generalization=GeneralizationState(str(data["generalization"])),
            evidence=tuple(EvidenceRef.from_dict(e) for e in data["evidence"]),  # type: ignore[arg-type,index]
            counterevidence=tuple(EvidenceRef.from_dict(e) for e in data["counterevidence"]),  # type: ignore[arg-type,index]
            dependencies=tuple(KnowledgeReference.from_dict(d) for d in data["dependencies"]),  # type: ignore[arg-type,index]
            system_version=str(data["system_version"]),
            created_utc=str(data["created_utc"]),
            provenance=str(data["provenance"]),
        )


def cap_confidence(
    profile: UncertaintyProfile,
    dependency_confidences: Sequence[Confidence] = (),
) -> Confidence:
    """Overall confidence = min(domain ceiling, weakest dependency confidence)."""
    floor = profile.ceiling.value
    if dependency_confidences:
        floor = min(floor, *(c.value for c in dependency_confidences))
    return Confidence(floor)

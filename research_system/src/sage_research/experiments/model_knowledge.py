"""Build Layer-1 Model Knowledge records from an ArchitectureMap.

The produced records are deterministic (content-addressed ids) and each is
validated against the core invariant: confidence never exceeds the weakest
dependency (the weakest uncertainty domain AND the weakest knowledge record it
depends on).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..domain.architecture_map import ArchitectureMap
from ..domain.confidence import Confidence, UncertaintyDomain, UncertaintyProfile
from ..domain.knowledge import (
    EvidenceCategory,
    EvidenceRef,
    EvidenceStrength,
    GeneralizationState,
    KnowledgeLayer,
    KnowledgeRecord,
    KnowledgeReference,
    KnowledgeState,
    ReplicationStatus,
    cap_confidence,
    stable_knowledge_id,
)

# Method confidence for a direct, single-pass architecture inspection.
# Not 1.0: artifact resolution (version/provenance) and loader fidelity are
# never perfectly certain.
_METHOD_CONFIDENCE = Confidence(0.95)
# Model confidence for claims that rest on the artifact provenance (identity).
_IDENTITY_MODEL_CONFIDENCE = Confidence(0.95)
# Model confidence for claims we measure directly on the loaded weights.
_MEASURED_MODEL_CONFIDENCE = Confidence(1.0)


def build_model_knowledge(
    amap: ArchitectureMap,
    report_id: str,
    system_version: str,
    created_utc: str,
) -> tuple[KnowledgeRecord, ...]:
    """Derive Model Knowledge records from an architecture map.

    Returns a tuple whose first element is the identity claim; every other
    record depends on it, demonstrating dependency-capped confidence.
    """
    subject = amap.model_identity.slug
    evidence = EvidenceRef(
        source_kind="architecture_inspection",
        source_id=report_id,
        category=EvidenceCategory.ARCHITECTURE,
        strength=EvidenceStrength.CONFIRMED,
        description=(
            "Direct inspection of the loaded artifact (module tree, parameter "
            "shapes, and configuration)."
        ),
        timestamp_utc=created_utc,
    )

    identity_domains = {
        UncertaintyDomain.MODEL: _IDENTITY_MODEL_CONFIDENCE,
        UncertaintyDomain.METHOD: _METHOD_CONFIDENCE,
    }
    identity_profile = UncertaintyProfile(identity_domains)
    identity_confidence = cap_confidence(identity_profile, ())

    identity_claim_text = _identity_claim_text(amap)
    identity = _make(
        subject=subject,
        claim=identity_claim_text,
        state=KnowledgeState.CONFIRMED,
        profile=identity_domains,
        confidence=identity_confidence,
        evidence=evidence,
        dependencies=(),
        system_version=system_version,
        created_utc=created_utc,
    )
    records: list[KnowledgeRecord] = [identity]
    dep = (KnowledgeReference(identity.knowledge_id, KnowledgeLayer.MODEL),)

    measured_domains = {
        UncertaintyDomain.MODEL: _MEASURED_MODEL_CONFIDENCE,
        UncertaintyDomain.METHOD: _METHOD_CONFIDENCE,
    }
    measured_profile = UncertaintyProfile(measured_domains)
    measured_confidence = cap_confidence(measured_profile, (identity_confidence,))

    s = amap.summary
    facts: Sequence[tuple[str, object]] = (
        ("architecture_label", s.architecture_label),
        ("total_parameters", s.total_parameters),
        ("num_layers", s.num_layers),
        ("hidden_size", s.hidden_size),
        ("vocab_size", s.vocab_size),
        ("num_attention_heads", s.num_attention_heads),
        ("head_dim", s.head_dim),
        ("intermediate_size", s.intermediate_size),
        ("layer_norm_epsilon", s.layer_norm_epsilon),
    )
    for key, value in facts:
        if value is None:
            continue
        records.append(
            _make(
                subject=subject,
                claim=f"{key} == {value}",
                state=KnowledgeState.CONFIRMED,
                profile=measured_domains,
                confidence=measured_confidence,
                evidence=evidence,
                dependencies=dep,
                system_version=system_version,
                created_utc=created_utc,
            )
        )

    for comp in amap.components:
        records.append(
            _make(
                subject=subject,
                claim=(
                    f"Component {comp.component_id} [{comp.kind.value}] "
                    f"class={comp.module_class} owns {comp.num_parameters} parameters"
                ),
                state=KnowledgeState.CONFIRMED,
                profile=measured_domains,
                confidence=measured_confidence,
                evidence=evidence,
                dependencies=dep,
                system_version=system_version,
                created_utc=created_utc,
            )
        )

    return tuple(records)


def _identity_claim_text(amap: ArchitectureMap) -> str:
    identity = amap.model_identity
    label = amap.summary.architecture_label or "unknown"
    return (
        f"Loaded artifact ({identity.source}) resolves to {identity.slug}; "
        f"architecture label {label!r}"
    )


def _make(
    *,
    subject: str,
    claim: str,
    state: KnowledgeState,
    profile: Mapping[UncertaintyDomain, Confidence],
    confidence: Confidence,
    evidence: EvidenceRef,
    dependencies: Sequence[KnowledgeReference],
    system_version: str,
    created_utc: str,
) -> KnowledgeRecord:
    return KnowledgeRecord(
        knowledge_id=stable_knowledge_id(subject, claim),
        layer=KnowledgeLayer.MODEL,
        subject=subject,
        claim=claim,
        state=state,
        uncertainty=UncertaintyProfile(profile),
        confidence=confidence,
        replication=ReplicationStatus.SINGLE_OBSERVATION,
        generalization=GeneralizationState.THIS_SPECIMEN,
        evidence=(evidence,),
        counterevidence=(),
        dependencies=tuple(dependencies),
        system_version=system_version,
        created_utc=created_utc,
        provenance="architecture_inspection",
    )

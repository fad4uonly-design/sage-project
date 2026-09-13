"""SAGE Research System — Model Lab.

An independent, packageable scientific research system that studies AI models
and records evidence about their mechanisms.

    Research Specimen 001 — Pythia-70M (architecture inspection milestone)

Architectural boundary (see ``docs/architecture.md`` for the full contract):

* This package is the **Research SAGE / Model Lab** only.
* It does NOT implement production SAGE mutation, autonomous self-rewriting,
  candidate production upgrades, fine-tuning, weight copying, or automatic
  production integration. Those belong to later stages and live elsewhere.
* It is deliberately runtime-agnostic: the research layer consumes a
  normalized ``LoadedModel`` contract and never imports Ollama/GGUF/Transformers
  internals directly. The eventual SAGE integration goes through the existing
  Model Integration Engine contracts.

Knowledge layers active for this milestone: Layer 1 (Model), Layer 2
(Mechanism), Layer 3 (Research). Layers 4 (Engineering) and 5 (Self) are dormant.
"""

from .domain.architecture_map import (
    ArchitectureMap,
    Component,
    ComponentKind,
    Connection,
    ConnectionKind,
    ModelSummary,
    ModuleInfo,
    ParameterInfo,
)
from .domain.confidence import Confidence, UncertaintyDomain, UncertaintyProfile
from .domain.knowledge import (
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
    utcnow_iso,
)
from .domain.mechanism import Edge, MechanismGraph, Node, NodeKind, Scope
from .domain.model_artifact import LoadOptions, ModelArtifact, ModelFormat, ModelIdentity
from .version import __version__

__all__ = [
    "__version__",
    # confidence / uncertainty
    "Confidence",
    "UncertaintyDomain",
    "UncertaintyProfile",
    # knowledge
    "KnowledgeLayer",
    "KnowledgeState",
    "ReplicationStatus",
    "GeneralizationState",
    "EvidenceCategory",
    "EvidenceStrength",
    "EvidenceRef",
    "KnowledgeReference",
    "KnowledgeRecord",
    "stable_knowledge_id",
    "cap_confidence",
    "utcnow_iso",
    # model artifact / identity
    "ModelFormat",
    "ModelIdentity",
    "ModelArtifact",
    "LoadOptions",
    # architecture map
    "ParameterInfo",
    "ModuleInfo",
    "ComponentKind",
    "ConnectionKind",
    "Component",
    "Connection",
    "ModelSummary",
    "ArchitectureMap",
    # mechanism graph scaffolding
    "NodeKind",
    "Scope",
    "Node",
    "Edge",
    "MechanismGraph",
]

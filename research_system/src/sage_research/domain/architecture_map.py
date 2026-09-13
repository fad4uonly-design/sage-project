"""Architecture map — a structured, evidence-grade description of a loaded model.

Pure data: no model-specific logic lives here. Component kinds and summary
fields are *produced* by an inspector (application layer) and merely *stored*
here. Connections in this map are structural/architectural relationships, never
causal claims (causal evidence lives in the mechanism graph, Layer 2).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .collections import ImmutableMap
from .model_artifact import ModelIdentity


class ComponentKind(StrEnum):
    """Generic architectural component vocabulary (architecture-neutral)."""

    EMBEDDING = "embedding"
    ATTENTION = "attention"
    FEEDFORWARD = "feedforward"
    NORMALIZATION = "normalization"
    OUTPUT_HEAD = "output_head"
    BLOCK = "block"
    OTHER = "other"


class ConnectionKind(StrEnum):
    """Kinds of structural relationship between components.

    NOTE: these are architectural adjacency relationships, NOT causal claims.
    """

    FEEDS_INTO = "feeds_into"
    RESIDUAL = "residual"
    SHARES_WEIGHTS = "shares_weights"
    PARALLEL = "parallel"


@dataclass(frozen=True)
class ParameterInfo:
    name: str
    shape: tuple[int, ...]
    dtype: str
    numel: int
    requires_grad: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "shape": list(self.shape),
            "dtype": self.dtype,
            "numel": self.numel,
            "requires_grad": self.requires_grad,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ParameterInfo:
        return cls(
            name=str(data["name"]),
            shape=tuple(int(x) for x in data["shape"]),  # type: ignore[arg-type]
            dtype=str(data["dtype"]),
            numel=int(data["numel"]),
            requires_grad=bool(data["requires_grad"]),
        )


@dataclass(frozen=True)
class ModuleInfo:
    """One module in the loaded model's module tree."""

    name: str
    class_name: str
    num_parameters: int
    child_names: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "class_name": self.class_name,
            "num_parameters": self.num_parameters,
            "child_names": list(self.child_names),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ModuleInfo:
        return cls(
            name=str(data["name"]),
            class_name=str(data["class_name"]),
            num_parameters=int(data["num_parameters"]),
            child_names=tuple(str(x) for x in data["child_names"]),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class Component:
    """A named architectural component (a leaf parameter group or a block)."""

    component_id: str
    name: str
    kind: ComponentKind
    module_class: str
    parameters: tuple[ParameterInfo, ...] = ()
    attributes: ImmutableMap = ImmutableMap()

    @property
    def num_parameters(self) -> int:
        return sum(p.numel for p in self.parameters)

    def to_dict(self) -> dict[str, object]:
        return {
            "component_id": self.component_id,
            "name": self.name,
            "kind": self.kind.value,
            "module_class": self.module_class,
            "parameters": [p.to_dict() for p in self.parameters],
            "attributes": self.attributes.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Component:
        return cls(
            component_id=str(data["component_id"]),
            name=str(data["name"]),
            kind=ComponentKind(str(data["kind"])),
            module_class=str(data["module_class"]),
            parameters=tuple(ParameterInfo.from_dict(p) for p in data["parameters"]),  # type: ignore[arg-type]
            attributes=ImmutableMap.from_dict(data["attributes"]),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class Connection:
    """A structural relationship between two components."""

    source_id: str
    target_id: str
    kind: ConnectionKind
    note: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "kind": self.kind.value,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> Connection:
        return cls(
            source_id=data["source_id"],
            target_id=data["target_id"],
            kind=ConnectionKind(data["kind"]),
            note=data.get("note", ""),
        )


@dataclass(frozen=True)
class ModelSummary:
    """Scalar summary of a loaded model's architecture."""

    total_parameters: int
    trainable_parameters: int
    num_modules: int
    architecture_label: str | None = None
    hidden_size: int | None = None
    num_layers: int | None = None
    vocab_size: int | None = None
    num_attention_heads: int | None = None
    head_dim: int | None = None
    intermediate_size: int | None = None
    layer_norm_epsilon: float | None = None
    extra: ImmutableMap = ImmutableMap()

    def to_dict(self) -> dict[str, object]:
        return {
            "total_parameters": self.total_parameters,
            "trainable_parameters": self.trainable_parameters,
            "num_modules": self.num_modules,
            "architecture_label": self.architecture_label,
            "hidden_size": self.hidden_size,
            "num_layers": self.num_layers,
            "vocab_size": self.vocab_size,
            "num_attention_heads": self.num_attention_heads,
            "head_dim": self.head_dim,
            "intermediate_size": self.intermediate_size,
            "layer_norm_epsilon": self.layer_norm_epsilon,
            "extra": self.extra.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ModelSummary:
        def _opt_int(key: str) -> int | None:
            v = data.get(key)
            return None if v is None else int(v)

        def _opt_float(key: str) -> float | None:
            v = data.get(key)
            return None if v is None else float(v)

        return cls(
            total_parameters=int(data["total_parameters"]),
            trainable_parameters=int(data["trainable_parameters"]),
            num_modules=int(data["num_modules"]),
            architecture_label=data.get("architecture_label") if data.get("architecture_label") is not None else None,
            hidden_size=_opt_int("hidden_size"),
            num_layers=_opt_int("num_layers"),
            vocab_size=_opt_int("vocab_size"),
            num_attention_heads=_opt_int("num_attention_heads"),
            head_dim=_opt_int("head_dim"),
            intermediate_size=_opt_int("intermediate_size"),
            layer_norm_epsilon=_opt_float("layer_norm_epsilon"),
            extra=ImmutableMap.from_dict(data.get("extra") or {}),
        )


@dataclass(frozen=True)
class ArchitectureMap:
    """A structured description of a loaded model's architecture.

    Produced by an :class:`~sage_research.interfaces.inspector.ArchitectureInspector`
    from a normalized :class:`~sage_research.interfaces.model_loader.LoadedModel`.
    """

    model_identity: ModelIdentity
    summary: ModelSummary
    components: tuple[Component, ...]
    connections: tuple[Connection, ...]
    created_utc: str
    generated_by: str

    def component(self, component_id: str) -> Component | None:
        for c in self.components:
            if c.component_id == component_id:
                return c
        return None

    def components_by_kind(self, kind: ComponentKind) -> tuple[Component, ...]:
        return tuple(c for c in self.components if c.kind == kind)

    def component_kind_counts(self) -> dict[ComponentKind, int]:
        counts: dict[ComponentKind, int] = {}
        for c in self.components:
            counts[c.kind] = counts.get(c.kind, 0) + 1
        return counts

    def total_parameters(self) -> int:
        return self.summary.total_parameters

    def orphan_connections(self) -> tuple[Connection, ...]:
        """Connections whose endpoints are not present in ``components``."""
        ids = {c.component_id for c in self.components}
        return tuple(
            conn for conn in self.connections
            if conn.source_id not in ids or conn.target_id not in ids
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "model_identity": self.model_identity.to_dict(),
            "summary": self.summary.to_dict(),
            "components": [c.to_dict() for c in self.components],
            "connections": [c.to_dict() for c in self.connections],
            "created_utc": self.created_utc,
            "generated_by": self.generated_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ArchitectureMap:
        return cls(
            model_identity=ModelIdentity.from_dict(data["model_identity"]),  # type: ignore[arg-type]
            summary=ModelSummary.from_dict(data["summary"]),  # type: ignore[arg-type]
            components=tuple(Component.from_dict(c) for c in data["components"]),  # type: ignore[arg-type]
            connections=tuple(Connection.from_dict(c) for c in data["connections"]),  # type: ignore[arg-type]
            created_utc=str(data["created_utc"]),
            generated_by=str(data["generated_by"]),
        )

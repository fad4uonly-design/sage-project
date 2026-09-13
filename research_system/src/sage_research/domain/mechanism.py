"""Mechanism graph — Layer 2 data scaffolding (NOT yet populated in this milestone).

This module defines the *vocabulary and container* for the mechanism graph so
that the foundation never needs restructuring later:

* Distinct node kinds keep representation, transformation, capability/behavior,
  and component claims separate — a component is never fused with a function.
* ``Scope`` keeps model-specific mechanisms distinct from abstract mechanisms.
* Edges are many-to-many and ALWAYS carry an :class:`EvidenceRef`; the evidence
  *category* (not the relation word) decides whether an edge may be treated as
  causal. Correlation is never automatically causation.

No inference, extraction, or analysis logic lives here. Population happens in
later milestones (activation, representation, and causal research).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .knowledge import EvidenceRef, KnowledgeLayer


class NodeKind(StrEnum):
    COMPONENT = "component"
    MECHANISM = "mechanism"
    CAPABILITY = "capability"
    BEHAVIOR = "behavior"
    REPRESENTATION = "representation"
    TRANSFORMATION = "transformation"


class Scope(StrEnum):
    """Model-specific mechanisms and abstract mechanisms must remain distinct."""

    MODEL_SPECIFIC = "model_specific"
    ABSTRACT = "abstract"


@dataclass(frozen=True)
class Node:
    node_id: str
    kind: NodeKind
    label: str
    scope: Scope
    layer: KnowledgeLayer
    model_subject: str | None = None   # set for MODEL_SPECIFIC nodes


@dataclass(frozen=True)
class Edge:
    """A many-to-many relationship between nodes, always backed by evidence.

    ``relation`` is open vocabulary (e.g. ``"implements"``, ``"causes"``,
    ``"correlates_with"``). The evidence category decides whether the edge may
    be treated as causal; a ``correlates_with`` edge must not be treated as
    causation regardless of its relation string.
    """

    edge_id: str
    source_id: str
    target_id: str
    relation: str
    evidence: EvidenceRef


@dataclass
class MechanismGraph:
    """Minimal typed container for the mechanism graph (many-to-many).

    Explicit mutable object (never hidden global state). Supports adding typed
    nodes and evidence-backed edges and querying neighborhoods.
    """

    nodes: dict[str, Node] = field(default_factory=dict)
    edges: dict[str, Edge] = field(default_factory=dict)

    def add_node(self, node: Node) -> Node:
        self.nodes[node.node_id] = node
        return node

    def add_edge(self, edge: Edge) -> Edge:
        if edge.source_id not in self.nodes:
            raise KeyError(f"edge source node not found: {edge.source_id!r}")
        if edge.target_id not in self.nodes:
            raise KeyError(f"edge target node not found: {edge.target_id!r}")
        self.edges[edge.edge_id] = edge
        return edge

    def neighbors(self, node_id: str) -> set[str]:
        """All nodes adjacent to ``node_id`` (in either direction)."""
        result: set[str] = set()
        for edge in self.edges.values():
            if edge.source_id == node_id:
                result.add(edge.target_id)
            elif edge.target_id == node_id:
                result.add(edge.source_id)
        return result

    def edges_between(self, a: str, b: str) -> tuple[Edge, ...]:
        """All edges connecting ``a`` and ``b`` in either direction (many-to-many)."""
        return tuple(
            e for e in self.edges.values()
            if {e.source_id, e.target_id} == {a, b}
        )

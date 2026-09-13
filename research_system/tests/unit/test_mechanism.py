import pytest
from sage_research.domain.knowledge import (
    EvidenceCategory,
    EvidenceRef,
    EvidenceStrength,
    KnowledgeLayer,
)
from sage_research.domain.mechanism import Edge, MechanismGraph, Node, NodeKind, Scope


def _evidence() -> EvidenceRef:
    return EvidenceRef(
        source_kind="unit_test",
        source_id="rpt-0",
        category=EvidenceCategory.CORRELATIONAL,
        strength=EvidenceStrength.WEAK,
        description="test evidence",
        timestamp_utc="2026-01-01T00:00:00+00:00",
    )


def test_many_to_many_relationships():
    graph = MechanismGraph()
    comp = Node("c1", NodeKind.COMPONENT, "attention", Scope.MODEL_SPECIFIC, KnowledgeLayer.MECHANISM, "s")
    rep = Node("r1", NodeKind.REPRESENTATION, "name-mover heads", Scope.MODEL_SPECIFIC, KnowledgeLayer.MECHANISM, "s")
    mech = Node("m1", NodeKind.MECHANISM, "induction", Scope.ABSTRACT, KnowledgeLayer.MECHANISM)
    for node in (comp, rep, mech):
        graph.add_node(node)

    graph.add_edge(Edge("e1", "c1", "r1", "correlates_with", _evidence()))
    graph.add_edge(Edge("e2", "c1", "r1", "causes", _evidence()))
    graph.add_edge(Edge("e3", "r1", "m1", "implements", _evidence()))

    # many-to-many: multiple edges between the same pair are allowed
    assert len(graph.edges_between("c1", "r1")) == 2
    assert graph.neighbors("c1") == {"r1"}
    assert graph.neighbors("r1") == {"c1", "m1"}


def test_edge_requires_existing_endpoints():
    graph = MechanismGraph()
    graph.add_node(Node("c1", NodeKind.COMPONENT, "x", Scope.MODEL_SPECIFIC, KnowledgeLayer.MECHANISM, "s"))
    with pytest.raises(KeyError):
        graph.add_edge(Edge("e1", "c1", "missing", "correlates_with", _evidence()))
    with pytest.raises(KeyError):
        graph.add_edge(Edge("e1", "missing", "c1", "correlates_with", _evidence()))


def test_scope_and_kinds_are_distinct():
    # Model-specific and abstract mechanisms remain distinct; component is not a function.
    assert Scope.MODEL_SPECIFIC != Scope.ABSTRACT
    assert NodeKind.COMPONENT != NodeKind.MECHANISM
    assert NodeKind.REPRESENTATION != NodeKind.TRANSFORMATION

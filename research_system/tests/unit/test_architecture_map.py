from sage_research.domain.architecture_map import (
    ArchitectureMap,
    Component,
    ComponentKind,
    Connection,
    ConnectionKind,
    ModelSummary,
    ParameterInfo,
)
from sage_research.domain.collections import ImmutableMap
from sage_research.domain.model_artifact import ModelIdentity


def _identity() -> ModelIdentity:
    return ModelIdentity(family="fake", name="n", version="v", source="s")


def _component(cid: str, kind: ComponentKind, numel: int) -> Component:
    return Component(
        component_id=cid,
        name=cid,
        kind=kind,
        module_class="Linear",
        parameters=(ParameterInfo(name=f"{cid}.w", shape=(numel,), dtype="float32", numel=numel),),
    )


def _map() -> ArchitectureMap:
    comps = (
        _component("cmp-0000", ComponentKind.EMBEDDING, 10),
        _component("cmp-0001", ComponentKind.BLOCK, 0),
        _component("cmp-0002", ComponentKind.ATTENTION, 30),
        _component("cmp-0003", ComponentKind.FEEDFORWARD, 20),
    )
    return ArchitectureMap(
        model_identity=_identity(),
        summary=ModelSummary(total_parameters=60, trainable_parameters=60, num_modules=5),
        components=comps,
        connections=(Connection("cmp-0000", "cmp-0001", ConnectionKind.FEEDS_INTO),),
        created_utc="2026-01-01T00:00:00+00:00",
        generated_by="test",
    )


def test_component_num_parameters_sums_shapes():
    comp = _component("c", ComponentKind.ATTENTION, 12)
    assert comp.num_parameters == 12


def test_component_lookup_and_missing():
    amap = _map()
    assert amap.component("cmp-0002").kind == ComponentKind.ATTENTION
    assert amap.component("nope") is None


def test_components_by_kind():
    amap = _map()
    assert len(amap.components_by_kind(ComponentKind.BLOCK)) == 1


def test_kind_counts():
    amap = _map()
    counts = amap.component_kind_counts()
    assert counts[ComponentKind.EMBEDDING] == 1
    assert sum(counts.values()) == len(amap.components)


def test_orphan_connections_detected():
    amap = _map()
    assert len(amap.orphan_connections()) == 0
    broken = ArchitectureMap(
        model_identity=_identity(),
        summary=ModelSummary(total_parameters=0, trainable_parameters=0, num_modules=0),
        components=(),
        connections=(Connection("missing-a", "missing-b", ConnectionKind.FEEDS_INTO),),
        created_utc="2026-01-01T00:00:00+00:00",
        generated_by="test",
    )
    assert len(broken.orphan_connections()) == 1


def test_round_trip():
    amap = _map()
    restored = ArchitectureMap.from_dict(amap.to_dict())
    assert restored == amap


def test_immutable_map_behaviour():
    m = ImmutableMap({"b": 2, "a": "1", "flag": True, "none": None})
    assert m["a"] == "1"
    assert m["b"] == "2"
    assert m["flag"] == "true"
    assert m["none"] == "null"
    assert "a" in m
    assert "z" not in m
    assert m.get("z") is None
    assert list(m.items()) == [("a", "1"), ("b", "2"), ("flag", "true"), ("none", "null")]
    assert ImmutableMap.from_dict(m.to_dict()) == m


def test_immutable_map_is_hashable():
    a = ImmutableMap({"x": "1"})
    b = ImmutableMap({"x": "1"})
    assert a == b
    assert hash(a) == hash(b)

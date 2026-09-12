"""DI container tests."""

from __future__ import annotations

import pytest
from sage.core.container import Container, ContainerError


def test_register_and_resolve_instance() -> None:
    c = Container()
    c.register_instance(str, "hello")
    assert c.resolve(str) == "hello"


def test_factory_lazy_singleton() -> None:
    c = Container()
    calls = {"n": 0}

    def factory(_c: Container) -> list[int]:
        calls["n"] += 1
        return [1, 2, 3]

    c.register_factory(list, factory)
    a = c.resolve(list)
    b = c.resolve(list)
    assert a is b
    assert calls["n"] == 1


def test_missing_service() -> None:
    c = Container()
    with pytest.raises(ContainerError):
        c.resolve(dict)


def test_named_services() -> None:
    c = Container()
    c.register_instance(str, "a", name="one")
    c.register_instance(str, "b", name="two")
    assert c.resolve(str, name="one") == "a"
    assert c.resolve(str, name="two") == "b"

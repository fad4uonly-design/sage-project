"""Small immutable collection helpers used across the domain layer."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType


@dataclass(frozen=True)
class ImmutableMap:
    """A hashable, read-only string -> string map.

    Used for attribute bags (model config, environment facts, rerun options)
    so that evidence-bearing records remain deeply immutable where appropriate.
    Values are stringified on construction; this keeps the type homogeneous and
    JSON-friendly while staying runtime-agnostic.
    """

    _items: tuple[tuple[str, str], ...] = field(default=(), repr=False)

    def __init__(self, items: Mapping[str, object] | None = None) -> None:
        if items is None:
            pairs: tuple[tuple[str, str], ...] = ()
        else:
            pairs = tuple(sorted((str(k), _stringify(v)) for k, v in items.items()))
        object.__setattr__(self, "_items", pairs)

    def get(self, key: str, default: str | None = None) -> str | None:
        for k, v in self._items:
            if k == key:
                return v
        return default

    def __getitem__(self, key: str) -> str:
        value = self.get(key)
        if value is None:
            raise KeyError(key)
        return value

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None

    def __iter__(self) -> Iterator[str]:
        return (k for k, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def items(self) -> tuple[tuple[str, str], ...]:
        return self._items

    def to_mapping(self) -> Mapping[str, str]:
        return MappingProxyType(dict(self._items))

    def to_dict(self) -> dict[str, str]:
        return dict(self._items)

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> ImmutableMap:
        return cls(data)

    def __bool__(self) -> bool:
        return bool(self._items)


def _stringify(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return str(value)

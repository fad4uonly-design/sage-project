"""
Lightweight Result type for expected domain outcomes.

Prefer Result for recoverable domain failures; raise exceptions for
programming errors and truly unexpected conditions.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import NoReturn, TypeVar

T = TypeVar("T")
E = TypeVar("E")
U = TypeVar("U")


@dataclass(frozen=True, slots=True)
class Ok[T]:
    value: T

    @property
    def is_ok(self) -> bool:
        return True

    @property
    def is_err(self) -> bool:
        return False

    def map(self, fn: Callable[[T], U]) -> Result[U, E]:
        return Ok(fn(self.value))

    def unwrap(self) -> T:
        return self.value


@dataclass(frozen=True, slots=True)
class Err[E]:
    error: E

    @property
    def is_ok(self) -> bool:
        return False

    @property
    def is_err(self) -> bool:
        return True

    def map(self, fn: Callable[[T], U]) -> Result[U, E]:
        return Err(self.error)

    def unwrap(self) -> NoReturn:
        raise ValueError(f"Called unwrap on Err: {self.error!r}")


Result = Ok[T] | Err[E]

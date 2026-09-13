"""Confidence and the three uncertainty domains.

Invariant enforced here and reused everywhere: **confidence must never exceed
the weakest dependency.** A claim's overall confidence is bounded by the
minimum of (a) every uncertainty domain it depends on, and (b) the confidence
of every knowledge record it depends on.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType


class UncertaintyDomain(StrEnum):
    """The three uncertainty domains.

    * ``MODEL``  — how sure we are about the model itself (identity, version,
      provenance, measurement fidelity).
    * ``METHOD`` — how sure we are that the research method measures what it
      claims to measure.
    * ``SAGE``   — SAGE self-uncertainty. DORMANT for Research Specimen 001
      (Layers 1–3); it is therefore omitted from profiles where it does not
      constrain the claim, so it never spuriously lowers confidence.
    """

    MODEL = "model"
    METHOD = "method"
    SAGE = "sage"


@dataclass(frozen=True)
class Confidence:
    """A probability-like value in ``[0, 1]``."""

    value: float

    def __post_init__(self) -> None:
        if not (0.0 <= self.value <= 1.0):
            raise ValueError(f"confidence must be in [0, 1], got {self.value!r}")

    def __str__(self) -> str:
        return f"{self.value:.4f}"

    def to_dict(self) -> float:
        return self.value

    @classmethod
    def from_dict(cls, data: float) -> Confidence:
        return cls(float(data))


@dataclass(frozen=True)
class UncertaintyProfile:
    """Per-domain confidence components plus the resulting ceiling.

    Immutable; the internal representation is a sorted tuple of pairs so the
    value is hashable and safely comparable.
    """

    _components: tuple[tuple[UncertaintyDomain, Confidence], ...]

    def __init__(self, domains: Mapping[UncertaintyDomain, Confidence]) -> None:
        if not domains:
            raise ValueError("an UncertaintyProfile needs at least one domain")
        object.__setattr__(
            self,
            "_components",
            tuple(sorted(domains.items(), key=lambda kv: kv[0].value)),
        )

    def get(self, domain: UncertaintyDomain) -> Confidence:
        for d, c in self._components:
            if d == domain:
                return c
        # Dormant / non-dependency domains do not constrain the claim.
        return Confidence(1.0)

    @property
    def components(self) -> Mapping[UncertaintyDomain, Confidence]:
        return MappingProxyType(dict(self._components))

    @property
    def ceiling(self) -> Confidence:
        """The strongest confidence this profile can support = weakest domain."""
        return Confidence(min(c.value for _, c in self._components))

    def to_dict(self) -> dict[str, float]:
        return {d.value: c.value for d, c in self._components}

    @classmethod
    def from_dict(cls, data: Mapping[str, float]) -> UncertaintyProfile:
        return cls({UncertaintyDomain(k): Confidence(float(v)) for k, v in data.items()})


def weakest_dependency(*values: Confidence) -> Confidence:
    """Return the minimum of the supplied confidence values.

    Raises if no values are given, so a missing dependency can never silently
    resolve to full confidence.
    """
    if not values:
        raise ValueError("at least one dependency is required")
    return Confidence(min(v.value for v in values))

"""Health status models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class HealthLevel(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class HealthStatus:
    """Health of a single module."""

    name: str
    level: HealthLevel = HealthLevel.UNKNOWN
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    critical: bool = False

    @property
    def ok(self) -> bool:
        return self.level in (HealthLevel.HEALTHY, HealthLevel.DEGRADED) or (
            self.level == HealthLevel.DEGRADED
        )

    @property
    def is_healthy(self) -> bool:
        return self.level == HealthLevel.HEALTHY

    @classmethod
    def healthy(cls, name: str, message: str = "ok", **details: Any) -> HealthStatus:
        return cls(name=name, level=HealthLevel.HEALTHY, message=message, details=details)

    @classmethod
    def degraded(cls, name: str, message: str, **details: Any) -> HealthStatus:
        return cls(name=name, level=HealthLevel.DEGRADED, message=message, details=details)

    @classmethod
    def unhealthy(cls, name: str, message: str, *, critical: bool = False, **details: Any) -> HealthStatus:
        return cls(
            name=name,
            level=HealthLevel.UNHEALTHY,
            message=message,
            critical=critical,
            details=details,
        )


@dataclass(slots=True)
class SystemHealth:
    """Aggregate health across all modules."""

    level: HealthLevel
    modules: list[HealthStatus] = field(default_factory=list)
    message: str = ""

    @property
    def is_healthy(self) -> bool:
        return self.level == HealthLevel.HEALTHY

    @property
    def is_ready(self) -> bool:
        """Ready means no critical module is unhealthy."""
        return not any(m.critical and m.level == HealthLevel.UNHEALTHY for m in self.modules)

    @classmethod
    def from_modules(cls, modules: list[HealthStatus]) -> SystemHealth:
        if not modules:
            return cls(level=HealthLevel.UNKNOWN, message="no modules")

        if any(m.level == HealthLevel.UNHEALTHY and m.critical for m in modules):
            level = HealthLevel.UNHEALTHY
            message = "critical module unhealthy"
        elif any(m.level == HealthLevel.UNHEALTHY for m in modules):
            level = HealthLevel.DEGRADED
            message = "non-critical module unhealthy"
        elif any(m.level == HealthLevel.DEGRADED for m in modules):
            level = HealthLevel.DEGRADED
            message = "one or more modules degraded"
        elif all(m.level == HealthLevel.HEALTHY for m in modules):
            level = HealthLevel.HEALTHY
            message = "all modules healthy"
        else:
            level = HealthLevel.UNKNOWN
            message = "incomplete health data"

        return cls(level=level, modules=list(modules), message=message)

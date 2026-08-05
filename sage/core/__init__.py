"""SAGE Core Engine — lifecycle, DI, modules, health."""

from sage.core.container import Container
from sage.core.engine import EngineState, SageEngine
from sage.core.health import HealthStatus, SystemHealth
from sage.core.module import BaseModule, ModuleState, SageModule

__all__ = [
    "BaseModule",
    "Container",
    "EngineState",
    "HealthStatus",
    "ModuleState",
    "SageEngine",
    "SageModule",
    "SystemHealth",
]

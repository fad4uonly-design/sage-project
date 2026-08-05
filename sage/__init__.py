"""
SAGE — Smart Autonomous General Engine
======================================

A personal AI operating system that learns, remembers, reasons, plans,
and assists through a modular, privacy-first architecture.
"""

from __future__ import annotations

__version__ = "0.3.0"
__tagline__ = "Learn Better. Think Better. Live Better."

from sage.core.engine import EngineState, SageEngine

__all__ = [
    "SageEngine",
    "EngineState",
    "__version__",
    "__tagline__",
]

"""
SAGE API Layer (v0.6.0) — versioned REST + WebSocket surface.

Public stability target for the v1.0 API freeze. Additive endpoints only
after freeze without major version bump.
"""

from sage.api.app import create_app
from sage.api.service import APIModule

__all__ = ["APIModule", "create_app"]

"""Permission Manager — capability grants for plugins and tools."""

from __future__ import annotations

from sage.permissions.interfaces import PermissionManager
from sage.permissions.models import Permission
from sage.permissions.service import PermissionsModule

__all__ = ["Permission", "PermissionManager", "PermissionsModule"]

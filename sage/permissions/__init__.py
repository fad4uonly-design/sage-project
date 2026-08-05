"""Permission Manager — capability grants for plugins and tools."""

from sage.permissions.interfaces import Permission, PermissionManager
from sage.permissions.service import PermissionsModule

__all__ = ["Permission", "PermissionManager", "PermissionsModule"]

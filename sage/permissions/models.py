"""Permission domain models."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso


class Permission(str, Enum):
    """Canonical capability tokens plugins/tools may request."""

    FILESYSTEM_READ = "filesystem.read"
    FILESYSTEM_WRITE = "filesystem.write"
    INTERNET = "internet"
    SHELL = "shell"
    DATABASE = "database"
    EMAIL = "email"
    CAMERA = "camera"
    MICROPHONE = "microphone"
    MEMORY_READ = "memory.read"
    MEMORY_WRITE = "memory.write"
    SECRETS_READ = "secrets.read"
    SECRETS_WRITE = "secrets.write"
    AGENTS_DISPATCH = "agents.dispatch"
    TOOLS_INVOKE = "tools.invoke"
    CONFIG_WRITE = "config.write"
    NOTIFICATIONS = "notifications"


# Dangerous permissions require explicit user grant; never auto-approve.
DANGEROUS_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.SHELL,
        Permission.INTERNET,
        Permission.FILESYSTEM_WRITE,
        Permission.SECRETS_READ,
        Permission.SECRETS_WRITE,
        Permission.DATABASE,
        Permission.CAMERA,
        Permission.MICROPHONE,
        Permission.EMAIL,
    }
)


class PrincipalType(str, Enum):
    PLUGIN = "plugin"
    TOOL = "tool"
    AGENT = "agent"
    USER = "user"
    SYSTEM = "system"


class PermissionGrant(BaseModel):
    id: str = Field(default_factory=lambda: new_id("perm"))
    principal: str
    principal_type: PrincipalType = PrincipalType.PLUGIN
    permission: Permission
    granted: bool = False
    reason: str | None = None
    granted_by: str = "user"
    created_at: str = Field(default_factory=utcnow_iso)
    updated_at: str = Field(default_factory=utcnow_iso)


class PermissionDenied(Exception):
    """Raised when a principal lacks a required permission."""

    def __init__(self, principal: str, permission: Permission | str, detail: str = "") -> None:
        self.principal = principal
        self.permission = permission
        self.detail = detail
        super().__init__(
            f"Permission denied: {principal} lacks {permission}"
            + (f" ({detail})" if detail else "")
        )

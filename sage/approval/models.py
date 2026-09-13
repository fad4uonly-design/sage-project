"""Approval domain models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from sage.utils.ids import new_id
from sage.utils.time import utcnow_iso


class ApprovalLevel(StrEnum):
    AUTOMATIC = "automatic"
    ASK_ONCE = "ask_once"
    ALWAYS_ASK = "always_ask"
    DENY = "deny"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    AUTO_APPROVED = "auto_approved"


class ApprovalPolicy(BaseModel):
    id: str = Field(default_factory=lambda: new_id("apol"))
    resource_type: str  # tool | skill | workflow | agent | filesystem
    resource_id: str  # name or id or "*"
    level: ApprovalLevel = ApprovalLevel.ASK_ONCE
    principal: str | None = None  # None = global default
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utcnow_iso)
    updated_at: str = Field(default_factory=utcnow_iso)


class ApprovalRequest(BaseModel):
    id: str = Field(default_factory=lambda: new_id("areq"))
    resource_type: str
    resource_id: str
    action: str
    level: ApprovalLevel
    status: ApprovalStatus = ApprovalStatus.PENDING
    principal: str = "user"
    reason: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    decided_by: str | None = None
    created_at: str = Field(default_factory=utcnow_iso)
    decided_at: str | None = None


class ApprovalDecision(BaseModel):
    allowed: bool
    status: ApprovalStatus
    request: ApprovalRequest | None = None
    message: str = ""

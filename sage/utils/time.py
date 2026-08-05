"""Time helpers — always UTC."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(UTC)


def utcnow_iso() -> str:
    """UTC now as ISO-8601 string with Z suffix."""
    return utcnow().isoformat().replace("+00:00", "Z")

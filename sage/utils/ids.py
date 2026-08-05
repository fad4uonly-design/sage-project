"""Identifier helpers."""

from __future__ import annotations

import uuid
from typing import Final

# Prefixes keep IDs human-skimmable in logs and DBs.
_PREFIXES: Final[dict[str, str]] = {
    "memory": "mem",
    "document": "doc",
    "chunk": "chk",
    "relation": "rel",
    "goal": "goal",
    "plan": "plan",
    "task": "task",
    "session": "ses",
    "turn": "trn",
    "agent": "agt",
    "event": "evt",
    "file": "fil",
    "plugin": "plg",
    "observation": "obs",
    "generic": "id",
}


def new_id(kind: str = "generic") -> str:
    """Return a unique string id, optionally prefixed by entity kind."""
    prefix = _PREFIXES.get(kind, kind[:8] if kind else "id")
    return f"{prefix}_{uuid.uuid4().hex}"

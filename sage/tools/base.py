"""Base tool with category, permissions, timeout metadata."""

from __future__ import annotations

from typing import Any

from sage.tools.interfaces import ToolResult


class BaseTool:
    name: str = "base"
    description: str = ""
    category: str = "general"
    parameters_schema: dict[str, Any] = {}
    permissions: list[str] = []
    timeout_seconds: float = 30.0

    async def execute(self, **params: Any) -> ToolResult:
        raise NotImplementedError

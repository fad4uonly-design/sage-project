"""Tool manager implementation."""

from __future__ import annotations

from typing import Any

from sage.logging import get_logger
from sage.tools.interfaces import Tool, ToolInfo, ToolResult

log = get_logger(__name__)


class DefaultToolManager:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        log.debug("tools.registered", name=tool.name)

    async def invoke(self, name: str, **params: Any) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(success=False, error=f"Unknown tool: {name}")
        try:
            return await tool.execute(**params)
        except Exception as exc:
            log.exception("tools.invoke_failed", name=name)
            return ToolResult(success=False, error=str(exc))

    def list_tools(self) -> list[ToolInfo]:
        return [
            ToolInfo(
                name=t.name,
                description=t.description,
                parameters_schema=dict(t.parameters_schema),
            )
            for t in self._tools.values()
        ]

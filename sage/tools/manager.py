"""Tool manager implementation with optional permission checks."""

from __future__ import annotations

from typing import Any

from sage.logging import get_logger
from sage.tools.interfaces import Tool, ToolInfo, ToolResult

log = get_logger(__name__)

# Tools that map to capability tokens
_TOOL_PERMISSIONS: dict[str, str] = {
    "shell": "shell",
    "http_request": "internet",
    "web_search": "internet",
}


class DefaultToolManager:
    def __init__(
        self,
        permission_manager: Any | None = None,
        *,
        principal: str = "core",
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self._permissions = permission_manager
        self._principal = principal

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        log.debug("tools.registered", name=tool.name)

    async def invoke(
        self,
        name: str,
        **params: Any,
    ) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(success=False, error=f"Unknown tool: {name}")

        required = _TOOL_PERMISSIONS.get(name)
        if required and self._permissions is not None:
            try:
                await self._permissions.require(self._principal, required)
            except Exception as exc:
                return ToolResult(success=False, error=str(exc))

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

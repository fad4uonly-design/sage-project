"""Tool protocols — extended for v0.4.0 Tool Framework."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    success: bool
    output: Any = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolInfo(BaseModel):
    name: str
    description: str
    category: str = "general"
    parameters_schema: dict[str, Any] = Field(default_factory=dict)
    permissions: list[str] = Field(default_factory=list)
    timeout_seconds: float = 30.0


@runtime_checkable
class Tool(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def parameters_schema(self) -> dict[str, Any]: ...

    async def execute(self, **params: Any) -> ToolResult: ...


@runtime_checkable
class ToolManager(Protocol):
    def register(self, tool: Tool) -> None: ...

    async def invoke(self, name: str, **params: Any) -> ToolResult: ...

    def list_tools(self) -> list[ToolInfo]: ...

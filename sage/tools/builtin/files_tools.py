"""File tools — read/write/list with permission metadata."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sage.tools.base import BaseTool
from sage.tools.interfaces import ToolResult


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read a UTF-8 text file from the local filesystem."
    category = "files"
    permissions = ["filesystem.read"]
    parameters_schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    async def execute(self, **params: Any) -> ToolResult:
        path = Path(str(params.get("path", ""))).expanduser()
        if not path.is_file():
            return ToolResult(success=False, error=f"Not a file: {path}")
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            return ToolResult(
                success=True,
                output=text,
                metadata={"path": str(path), "chars": len(text)},
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Write UTF-8 text to a local file (creates parents)."
    category = "files"
    permissions = ["filesystem.write"]
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    }

    async def execute(self, **params: Any) -> ToolResult:
        path = Path(str(params.get("path", ""))).expanduser()
        content = str(params.get("content", ""))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return ToolResult(
                success=True,
                output=str(path),
                metadata={"bytes": len(content.encode("utf-8"))},
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


class ListDirTool(BaseTool):
    name = "list_dir"
    description = "List entries in a directory."
    category = "files"
    permissions = ["filesystem.read"]
    parameters_schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    async def execute(self, **params: Any) -> ToolResult:
        path = Path(str(params.get("path", "."))).expanduser()
        if not path.is_dir():
            return ToolResult(success=False, error=f"Not a directory: {path}")
        entries = sorted(p.name + ("/" if p.is_dir() else "") for p in path.iterdir())
        return ToolResult(success=True, output=entries, metadata={"count": len(entries)})

"""Data / document / weather tools."""

from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path
from typing import Any

from sage.tools.base import BaseTool
from sage.tools.interfaces import ToolResult
from sage.utils.time import utcnow_iso


class WeatherTool(BaseTool):
    """Offline-friendly weather stub (replace with API tool when network allowed)."""

    name = "weather"
    description = "Weather snapshot for a location (stub/offline heuristic)."
    category = "weather"
    permissions = []  # stub is local
    parameters_schema = {
        "type": "object",
        "properties": {"location": {"type": "string"}},
    }

    async def execute(self, **params: Any) -> ToolResult:
        location = str(params.get("location") or "local").strip() or "local"
        # Deterministic pseudo weather from location hash
        h = sum(ord(c) for c in location.lower())
        temp = 18 + (h % 15)
        conditions = ["clear", "partly cloudy", "humid", "breezy", "overcast"][h % 5]
        out = {
            "location": location,
            "temp_c": temp,
            "conditions": conditions,
            "humidity_pct": 40 + (h % 50),
            "as_of": utcnow_iso(),
            "source": "stub",
        }
        return ToolResult(success=True, output=out)


class SqliteQueryTool(BaseTool):
    name = "sqlite_query"
    description = "Read-only SQL against a sqlite file (SELECT only)."
    category = "database"
    permissions = ["database"]
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "sql": {"type": "string"},
        },
        "required": ["path", "sql"],
    }

    async def execute(self, **params: Any) -> ToolResult:
        import sqlite3

        path = str(params.get("path", ""))
        sql = str(params.get("sql", "")).strip()
        if not sql.lower().startswith("select"):
            return ToolResult(success=False, error="Only SELECT statements allowed")
        try:
            con = sqlite3.connect(path)
            con.row_factory = sqlite3.Row
            cur = con.execute(sql)
            rows = [dict(r) for r in cur.fetchall()]
            con.close()
            return ToolResult(success=True, output=rows, metadata={"count": len(rows)})
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


class CsvSummaryTool(BaseTool):
    name = "csv_summary"
    description = "Summarize a CSV file (columns + row count + head)."
    category = "spreadsheet"
    permissions = ["filesystem.read"]
    parameters_schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}, "max_rows": {"type": "integer"}},
        "required": ["path"],
    }

    async def execute(self, **params: Any) -> ToolResult:
        path = Path(str(params.get("path", ""))).expanduser()
        max_rows = int(params.get("max_rows") or 5)
        if not path.is_file():
            return ToolResult(success=False, error=f"Missing file: {path}")
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            reader = csv.DictReader(StringIO(text))
            rows = []
            for i, row in enumerate(reader):
                if i < max_rows:
                    rows.append(row)
            # count all
            total = sum(1 for _ in csv.DictReader(StringIO(text)))
            return ToolResult(
                success=True,
                output={
                    "columns": reader.fieldnames,
                    "row_count": total,
                    "head": rows,
                },
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


class JsonLoadTool(BaseTool):
    name = "json_load"
    description = "Load a JSON file."
    category = "files"
    permissions = ["filesystem.read"]
    parameters_schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    async def execute(self, **params: Any) -> ToolResult:
        path = Path(str(params.get("path", ""))).expanduser()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return ToolResult(success=True, output=data)
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


class MarkdownToTextTool(BaseTool):
    name = "markdown_outline"
    description = "Extract heading outline from markdown text or file."
    category = "document"
    permissions = []
    parameters_schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}, "path": {"type": "string"}},
    }

    async def execute(self, **params: Any) -> ToolResult:
        text = str(params.get("text") or "")
        if not text and params.get("path"):
            p = Path(str(params["path"])).expanduser()
            text = p.read_text(encoding="utf-8", errors="replace")
        headings = []
        for line in text.splitlines():
            if line.startswith("#"):
                headings.append(line.strip())
        return ToolResult(success=True, output=headings)

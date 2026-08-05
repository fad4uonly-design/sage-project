"""Built-in tools."""

from sage.tools.builtin.core_tools import CalculatorTool, EchoTool, TimeTool
from sage.tools.builtin.data_tools import (
    CsvSummaryTool,
    JsonLoadTool,
    MarkdownToTextTool,
    SqliteQueryTool,
    WeatherTool,
)
from sage.tools.builtin.files_tools import ListDirTool, ReadFileTool, WriteFileTool

__all__ = [
    "CalculatorTool",
    "CsvSummaryTool",
    "EchoTool",
    "JsonLoadTool",
    "ListDirTool",
    "MarkdownToTextTool",
    "ReadFileTool",
    "SqliteQueryTool",
    "TimeTool",
    "WeatherTool",
    "WriteFileTool",
]


def all_builtin_tools() -> list:
    return [
        EchoTool(),
        TimeTool(),
        CalculatorTool(),
        ReadFileTool(),
        WriteFileTool(),
        ListDirTool(),
        WeatherTool(),
        SqliteQueryTool(),
        CsvSummaryTool(),
        JsonLoadTool(),
        MarkdownToTextTool(),
    ]

"""Safe built-in tools available by default."""

from __future__ import annotations

import ast
import operator
from typing import Any

from sage.tools.base import BaseTool
from sage.tools.interfaces import ToolResult
from sage.utils.time import utcnow_iso

_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}


class EchoTool(BaseTool):
    name = "echo"
    description = "Echo back the provided text."
    category = "utility"
    parameters_schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    async def execute(self, **params: Any) -> ToolResult:
        return ToolResult(success=True, output=str(params.get("text", "")))


class TimeTool(BaseTool):
    name = "current_time"
    description = "Return the current UTC time in ISO-8601 format."
    category = "utility"
    parameters_schema = {"type": "object", "properties": {}}

    async def execute(self, **params: Any) -> ToolResult:
        return ToolResult(success=True, output=utcnow_iso())


class CalculatorTool(BaseTool):
    name = "calculator"
    description = "Evaluate a simple arithmetic expression (safe AST evaluator)."
    category = "utility"
    parameters_schema = {
        "type": "object",
        "properties": {"expression": {"type": "string"}},
        "required": ["expression"],
    }

    async def execute(self, **params: Any) -> ToolResult:
        expr = str(params.get("expression", "")).strip()
        if not expr:
            return ToolResult(success=False, error="expression required")
        try:
            value = self._eval(ast.parse(expr, mode="eval").body)
            return ToolResult(success=True, output=value)
        except Exception as exc:
            return ToolResult(success=False, error=f"invalid expression: {exc}")

    def _eval(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPS:
            return _SAFE_OPS[type(node.op)](self._eval(node.left), self._eval(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPS:
            return _SAFE_OPS[type(node.op)](self._eval(node.operand))
        raise ValueError("unsupported expression")

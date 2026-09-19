"""Model-assisted tool selection — constrained JSON, no parallel tool pipeline.

SAGE resolves *explicit* tool imperatives deterministically in
:class:`~sage.orchestrator.intent.IntentAnalyzer` (``calculate 25 * 4``,
``learn about X``); those never reach this module and still make no model call.

This module covers only the remaining case: a turn where the conversation
policy already permits tools, but no explicit imperative matched, so SAGE has
to decide whether one of the *already registered* tools applies.

The decision is a genuine structured-output request: the JSON schema below is
passed through the existing :class:`CompletionRequest` (→ the model adapter's
``response_format``), so the model's reply is constrained to SAGE's existing
tool-call contract instead of free text that would have to be scraped.

Nothing here executes a tool. Execution stays exactly where it was — the
:class:`~sage.tools.interfaces.ToolManager` — so permissions, approval,
verification and audit are untouched, and a model can never reach a tool that
is not registered.
"""

from __future__ import annotations

import json
from typing import Any

from sage.logging import get_logger
from sage.models.interfaces import CompletionRequest, Message

log = get_logger(__name__)

#: Keeps a small local model's decision prompt bounded.
_DEFAULT_MAX_TOOLS = 20

#: The only tools a model decision may ever name: read-only, no side effects.
#: Everything else (file writes, HTTP, git, echo) stays reachable only through
#: explicit user imperatives, never through a small-model guess.
_AUTO_SELECTABLE = frozenset({"calculator", "current_time"})

_SYSTEM_PROMPT = (
    "You decide whether one of SAGE's registered tools is required to handle "
    "the user's request.\n"
    "Reply with the tool name and its arguments. Reply with null when the "
    "request is ordinary conversation, an explanation, or knowledge you can "
    "answer directly without a tool.\n"
    "Only the registered tools listed below exist; never invent a tool.\n"
)


def build_decision_schema(tool_names: list[str]) -> dict[str, Any]:
    """JSON schema for a tool decision, restricted to registered tools.

    Mirrors SAGE's existing tool-call contract — ``{"tool": ..., "arguments":
    {...}}`` — with ``null`` meaning "no tool applies".
    """
    return {
        "type": "object",
        "properties": {
            "tool": {
                "type": ["string", "null"],
                "enum": [*tool_names, None],
                "description": "Registered tool to use, or null when none applies.",
            },
            "arguments": {
                "type": "object",
                "description": "Arguments for the chosen tool (empty when null).",
            },
        },
        "required": ["tool", "arguments"],
        "additionalProperties": False,
    }


def _describe_tools(tools: list[Any]) -> str:
    """Render the existing tool registry as decision context (source of truth)."""
    lines: list[str] = []
    for info in tools:
        schema = info.parameters_schema or {}
        properties = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        arguments = ", ".join(
            f"{name}{' (required)' if name in required else ''}" for name in properties
        )
        lines.append(
            f"- {info.name}: {info.description}"
            f" | arguments: {arguments or 'none'}"
        )
    return "\n".join(lines)

def _parse_decision(
    content: str, tool_names: list[str]
) -> tuple[str, dict[str, Any]] | None:
    """Validate a constrained reply; return ``(tool, arguments)`` or ``None``.

    Anything unusable — malformed JSON, an unregistered tool, a null decision,
    a non-object argument map — yields ``None`` so the caller falls back to
    ordinary composition. Never raises.
    """
    try:
        data = json.loads(content or "")
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    name = data.get("tool")
    if not isinstance(name, str):
        return None
    name = name.strip()
    if name not in tool_names:
        return None

    arguments = data.get("arguments")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return None

    args = {
        str(key): value
        for key, value in arguments.items()
        if isinstance(key, str) and value is not None
    }
    return name, args


class ModelToolSelector:
    """Asks the configured model which registered tool (if any) applies.

    Uses the existing ``ModelRouter`` (so the configured local brain is the
    decider — the model layer stays interchangeable) and the existing
    ``ToolManager.list_tools()`` registry as the only source of tools.
    """

    def __init__(
        self,
        router: Any,
        tool_manager: Any,
        *,
        max_tools: int = _DEFAULT_MAX_TOOLS,
    ) -> None:
        self._router = router
        self._tools = tool_manager
        self._max_tools = max_tools

    @staticmethod
    def has_required_arguments(
        tool_manager: Any, name: str, arguments: dict[str, Any]
    ) -> bool:
        """True when every required argument for ``name`` was supplied.

        Enforces the existing registry contract up front so an under-specified
        decision falls back to ordinary composition instead of producing a
        known-failing tool call.
        """
        try:
            info = next(
                (i for i in tool_manager.list_tools() if i.name == name), None
            )
        except Exception:
            return False
        if info is None:
            return False
        required = (info.parameters_schema or {}).get("required") or []
        return all(key in arguments for key in required)

    async def decide(self, message: str) -> tuple[str, dict[str, Any]] | None:
        """Return ``(tool_name, arguments)`` when a registered tool applies."""
        try:
            tools = [
                info
                for info in self._tools.list_tools()
                if info.name in _AUTO_SELECTABLE
            ][: self._max_tools]
        except Exception:
            log.exception("tools.selection_registry_failed")
            return None
        if not tools:
            return None

        tool_names = [info.name for info in tools]
        request = CompletionRequest(
            messages=[
                Message(
                    role="system",
                    content=(
                        f"{_SYSTEM_PROMPT}\nRegistered tools:\n{_describe_tools(tools)}"
                    ),
                ),
                Message(role="user", content=message),
            ],
            temperature=0.0,
            response_schema=build_decision_schema(tool_names),
        )

        try:
            model = self._router.get_language_model()
            response = await model.complete(request)
        except Exception:
            # A failed decision must degrade to ordinary composition.
            log.exception("tools.selection_failed")
            return None

        decision = _parse_decision(getattr(response, "content", "") or "", tool_names)
        if decision is None:
            log.debug("tools.selection_none")
            return None
        log.info("tools.selection_made", tool=decision[0])
        return decision

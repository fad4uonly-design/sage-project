"""Tool manager — validation, permissions, approval, audit, timeout."""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any

from sage.logging import get_logger
from sage.tools.interfaces import Tool, ToolInfo, ToolResult
from sage.tools.verification import ToolOutputVerifier

log = get_logger(__name__)


class DefaultToolManager:
    def __init__(
        self,
        permission_manager: Any | None = None,
        *,
        principal: str = "core",
        approval_engine: Any | None = None,
        audit: Any | None = None,
        auto_approve_in_test: bool = False,
        verifier: ToolOutputVerifier | None = None,
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self._permissions = permission_manager
        self._principal = principal
        self._approval = approval_engine
        self._audit = audit
        self._auto_approve_in_test = auto_approve_in_test
        self._verifier = verifier

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        log.debug("tools.registered", name=tool.name)

    def _info(self, tool: Tool) -> ToolInfo:
        return ToolInfo(
            name=tool.name,
            description=tool.description,
            category=getattr(tool, "category", "general"),
            parameters_schema=dict(tool.parameters_schema or {}),
            permissions=list(getattr(tool, "permissions", []) or []),
            timeout_seconds=float(getattr(tool, "timeout_seconds", 30.0) or 30.0),
        )

    def list_tools(self) -> list[ToolInfo]:
        return [self._info(t) for t in self._tools.values()]

    async def invoke(self, name: str, **params: Any) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(success=False, error=f"Unknown tool: {name}")

        info = self._info(tool)
        # Validate required params lightly
        schema = info.parameters_schema or {}
        required = schema.get("required") or []
        for key in required:
            if key not in params:
                return ToolResult(success=False, error=f"Missing required parameter: {key}")

        # Permission checks
        for perm in info.permissions:
            if self._permissions is not None:
                try:
                    await self._permissions.require(self._principal, perm)
                except Exception as exc:
                    return ToolResult(success=False, error=str(exc))

        # Approval engine
        if self._approval is not None:
            try:
                decision = await self._approval.check(
                    "tool",
                    name,
                    "invoke",
                    principal=self._principal,
                    payload={"params_keys": list(params.keys())},
                    auto_approve_in_test=self._auto_approve_in_test,
                )
                if not decision.allowed:
                    return ToolResult(
                        success=False,
                        error=decision.message,
                        metadata={
                            "approval_status": decision.status.value,
                            "approval_request_id": decision.request.id
                            if decision.request
                            else None,
                        },
                    )
            except Exception as exc:
                log.exception("tools.approval_failed", name=name)
                return ToolResult(success=False, error=f"approval error: {exc}")

        t0 = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                tool.execute(**params),
                timeout=info.timeout_seconds,
            )
        except TimeoutError:
            result = ToolResult(success=False, error=f"Tool timed out after {info.timeout_seconds}s")
        except Exception as exc:
            log.exception("tools.invoke_failed", name=name)
            result = ToolResult(success=False, error=str(exc))

        # Tool-R0 verification gate: validate output before returning
        if self._verifier is not None:
            try:
                verification = await self._verifier.verify(name, result)
                result.metadata["verification"] = {
                    "verified": verification.verified,
                    "confidence": verification.confidence,
                    "issue_count": len(verification.issues),
                }
                if verification.issues:
                    result.metadata["verification_issues"] = [
                        {
                            "severity": issue.severity,
                            "category": issue.category,
                            "message": issue.message,
                            "field": issue.field,
                        }
                        for issue in verification.issues
                    ]
            except Exception as exc:
                log.exception("tools.verification_failed", name=name)
                # Verification failure doesn't block the tool result
                result.metadata["verification_error"] = str(exc)

        duration = (time.perf_counter() - t0) * 1000
        if self._audit is not None:
            with contextlib.suppress(Exception):
                await self._audit.record(
                    kind="tool",
                    tool_name=name,
                    principal=self._principal,
                    status="ok" if result.success else "error",
                    summary=f"tool {name}",
                    duration_ms=duration,
                    detail={"error": result.error} if result.error else {},
                )
        return result

"""Tool-R0 verification gate — validates outputs before final answer.

Phase 1.2 capability: verification layer between tool execution and final
answer. Validates tool outputs against schemas, checks evidence quality, and
gates the response with structured verification results.

The verifier is advisory by design: it flags suspicious outputs but never
blocks them silently. The orchestrator decides whether to surface warnings,
retry with constraints, or proceed. This keeps the gate transparent.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from sage.logging import get_logger
from sage.tools.interfaces import ToolResult

log = get_logger(__name__)


class VerificationIssue(BaseModel):
    """One detected issue in a tool output."""

    severity: str  # "warning" | "error"
    category: str
    message: str
    field: str | None = None


class VerificationResult(BaseModel):
    """Verification outcome for one tool invocation."""

    verified: bool
    issues: list[VerificationIssue] = Field(default_factory=list)
    confidence: float = 1.0  # 0..1, confidence in the verification itself


class ToolOutputVerifier:
    """Validates tool outputs against expectations before final answer."""

    def __init__(self, *, strict: bool = False) -> None:
        """Initialize verifier.

        Args:
            strict: When True, any verification issue fails verification.
                   When False (default), only errors fail; warnings pass with flags.
        """
        self._strict = strict

    async def verify(
        self,
        tool_name: str,
        result: ToolResult,
        *,
        expected_schema: dict[str, Any] | None = None,
    ) -> VerificationResult:
        """Verify a tool result before it reaches the final answer layer.

        Args:
            tool_name: Name of the tool that produced this result.
            result: The tool execution result to verify.
            expected_schema: Optional schema the output should conform to.

        Returns:
            VerificationResult with verified flag and any detected issues.
        """
        issues: list[VerificationIssue] = []

        # 1. Basic sanity: tool reported success but has error message
        if result.success and result.error:
            issues.append(
                VerificationIssue(
                    severity="warning",
                    category="inconsistent_status",
                    message=(
                        f"Tool '{tool_name}' reported success=True but included "
                        f"error message: {result.error}"
                    ),
                )
            )

        # 2. Failed execution should have error message
        if not result.success and not result.error:
            issues.append(
                VerificationIssue(
                    severity="error",
                    category="missing_error",
                    message=(
                        f"Tool '{tool_name}' reported failure but provided no error message"
                    ),
                )
            )

        # 3. Success should have output (unless tool explicitly returns None)
        if result.success and result.output is None and not result.metadata.get("empty_ok"):
            issues.append(
                VerificationIssue(
                    severity="warning",
                    category="empty_output",
                    message=(
                        f"Tool '{tool_name}' succeeded but returned no output"
                    ),
                )
            )

        # 4. Schema validation when provided
        if expected_schema and result.success and result.output is not None:
            schema_issues = self._validate_schema(result.output, expected_schema)
            issues.extend(schema_issues)

        # 5. Output type sanity checks
        if result.success and result.output is not None:
            type_issues = self._check_output_type(tool_name, result.output)
            issues.extend(type_issues)

        # Verification passes unless there are errors (or warnings in strict mode)
        has_errors = any(issue.severity == "error" for issue in issues)
        has_warnings = any(issue.severity == "warning" for issue in issues)
        verified = not has_errors and (not self._strict or not has_warnings)

        # Confidence degrades with warning count
        confidence = 1.0
        if has_warnings:
            confidence = max(0.5, 1.0 - (len([i for i in issues if i.severity == "warning"]) * 0.15))

        if issues:
            log.info(
                "tools.verification_completed",
                tool_name=tool_name,
                verified=verified,
                issue_count=len(issues),
                confidence=round(confidence, 2),
            )

        return VerificationResult(
            verified=verified,
            issues=issues,
            confidence=round(confidence, 2),
        )

    def _validate_schema(
        self,
        output: Any,
        schema: dict[str, Any],
    ) -> list[VerificationIssue]:
        """Validate output against expected schema (basic structural check)."""
        issues: list[VerificationIssue] = []

        # Handle dict outputs with required fields
        if isinstance(schema, dict) and schema.get("type") == "object":
            if not isinstance(output, dict):
                issues.append(
                    VerificationIssue(
                        severity="error",
                        category="schema_mismatch",
                        message=f"Expected object output, got {type(output).__name__}",
                    )
                )
                return issues

            required = schema.get("required", [])
            for field in required:
                if field not in output:
                    issues.append(
                        VerificationIssue(
                            severity="error",
                            category="missing_field",
                            message=f"Required field '{field}' missing from output",
                            field=field,
                        )
                    )

        return issues

    def _check_output_type(self, tool_name: str, output: Any) -> list[VerificationIssue]:
        """Basic output type sanity checks."""
        issues: list[VerificationIssue] = []

        # String outputs shouldn't be suspiciously short for certain tools
        if isinstance(output, str) and len(output.strip()) < 3 and tool_name not in {"ping", "health", "status"}:
                issues.append(
                    VerificationIssue(
                        severity="warning",
                        category="suspicious_output",
                        message=f"Output string unusually short for '{tool_name}': '{output}'",
                    )
                )

        # List outputs shouldn't be unexpectedly empty for retrieval-like tools
        if isinstance(output, list) and len(output) == 0 and any(
            keyword in tool_name.lower()
            for keyword in ["search", "list", "find", "retrieve"]
        ):
                issues.append(
                    VerificationIssue(
                        severity="warning",
                        category="empty_result",
                        message=f"Tool '{tool_name}' returned empty list (may indicate no results found)",
                    )
                )

        return issues


def build_verifier(*, strict: bool = False) -> ToolOutputVerifier:
    """Factory: builds default verifier with optional strict mode."""
    return ToolOutputVerifier(strict=strict)

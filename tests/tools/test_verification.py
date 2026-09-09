"""Tests for Tool-R0 verification gate."""

import pytest

from sage.tools.interfaces import ToolResult
from sage.tools.verification import ToolOutputVerifier, VerificationIssue


class TestToolOutputVerifier:
    """Test suite for Tool-R0 verification gate."""

    @pytest.fixture
    def verifier(self):
        return ToolOutputVerifier(strict=False)

    @pytest.fixture
    def strict_verifier(self):
        return ToolOutputVerifier(strict=True)

    @pytest.mark.asyncio
    async def test_successful_result_with_output(self, verifier):
        """Clean successful result passes verification."""
        result = ToolResult(success=True, output={"data": "valid"})
        verification = await verifier.verify("test_tool", result)

        assert verification.verified is True
        assert len(verification.issues) == 0
        assert verification.confidence == 1.0

    @pytest.mark.asyncio
    async def test_failed_result_with_error(self, verifier):
        """Failed result with error message passes verification."""
        result = ToolResult(success=False, error="connection timeout")
        verification = await verifier.verify("test_tool", result)

        assert verification.verified is True
        assert len(verification.issues) == 0

    @pytest.mark.asyncio
    async def test_inconsistent_status(self, verifier):
        """Success with error message raises warning but passes."""
        result = ToolResult(success=True, output="data", error="weird state")
        verification = await verifier.verify("test_tool", result)

        assert verification.verified is True  # warning doesn't fail in non-strict
        assert len(verification.issues) == 1
        assert verification.issues[0].severity == "warning"
        assert verification.issues[0].category == "inconsistent_status"
        assert verification.confidence < 1.0

    @pytest.mark.asyncio
    async def test_missing_error_message(self, verifier):
        """Failed result without error message fails verification."""
        result = ToolResult(success=False)
        verification = await verifier.verify("test_tool", result)

        assert verification.verified is False
        assert len(verification.issues) == 1
        assert verification.issues[0].severity == "error"
        assert verification.issues[0].category == "missing_error"

    @pytest.mark.asyncio
    async def test_empty_output_warning(self, verifier):
        """Successful result with None output raises warning."""
        result = ToolResult(success=True, output=None)
        verification = await verifier.verify("search_tool", result)

        assert verification.verified is True
        assert len(verification.issues) == 1
        assert verification.issues[0].severity == "warning"
        assert verification.issues[0].category == "empty_output"

    @pytest.mark.asyncio
    async def test_empty_output_allowed(self, verifier):
        """Empty output OK when metadata says so."""
        result = ToolResult(
            success=True,
            output=None,
            metadata={"empty_ok": True},
        )
        verification = await verifier.verify("test_tool", result)

        assert verification.verified is True
        assert len(verification.issues) == 0

    @pytest.mark.asyncio
    async def test_schema_validation_missing_field(self, verifier):
        """Missing required field fails schema validation."""
        result = ToolResult(success=True, output={"name": "test"})
        schema = {
            "type": "object",
            "required": ["name", "id"],
        }
        verification = await verifier.verify("test_tool", result, expected_schema=schema)

        assert verification.verified is False
        assert any(issue.category == "missing_field" for issue in verification.issues)
        assert any(issue.field == "id" for issue in verification.issues)

    @pytest.mark.asyncio
    async def test_schema_validation_wrong_type(self, verifier):
        """Output type mismatch fails schema validation."""
        result = ToolResult(success=True, output="string instead of object")
        schema = {"type": "object"}
        verification = await verifier.verify("test_tool", result, expected_schema=schema)

        assert verification.verified is False
        assert any(issue.category == "schema_mismatch" for issue in verification.issues)

    @pytest.mark.asyncio
    async def test_suspicious_short_string(self, verifier):
        """Suspiciously short string output raises warning."""
        result = ToolResult(success=True, output="ok")
        verification = await verifier.verify("complex_search", result)

        assert verification.verified is True
        assert any(issue.category == "suspicious_output" for issue in verification.issues)

    @pytest.mark.asyncio
    async def test_short_string_ok_for_status_tools(self, verifier):
        """Short string is fine for status/health checks."""
        result = ToolResult(success=True, output="ok")
        verification = await verifier.verify("health", result)

        assert verification.verified is True
        assert not any(issue.category == "suspicious_output" for issue in verification.issues)

    @pytest.mark.asyncio
    async def test_empty_list_warning_for_search(self, verifier):
        """Empty list from search tool raises warning."""
        result = ToolResult(success=True, output=[])
        verification = await verifier.verify("search_documents", result)

        assert verification.verified is True
        assert any(issue.category == "empty_result" for issue in verification.issues)

    @pytest.mark.asyncio
    async def test_strict_mode_fails_on_warnings(self, strict_verifier):
        """Strict mode fails verification on warnings."""
        result = ToolResult(success=True, output=None)
        verification = await strict_verifier.verify("test_tool", result)

        assert verification.verified is False
        assert any(issue.severity == "warning" for issue in verification.issues)

    @pytest.mark.asyncio
    async def test_confidence_degrades_with_warnings(self, verifier):
        """Multiple warnings reduce confidence score."""
        # Create result with multiple warning triggers
        result = ToolResult(success=True, output="ok", error="but also error")
        verification = await verifier.verify("search_tool", result)

        assert verification.verified is True
        assert verification.confidence < 1.0
        assert verification.confidence >= 0.5

    @pytest.mark.asyncio
    async def test_multiple_issues_tracked(self, verifier):
        """Verifier tracks all detected issues."""
        result = ToolResult(success=True, output=None, error="inconsistent")
        verification = await verifier.verify("search_tool", result)

        assert len(verification.issues) >= 2  # inconsistent status + empty output
        categories = {issue.category for issue in verification.issues}
        assert "inconsistent_status" in categories
        assert "empty_output" in categories

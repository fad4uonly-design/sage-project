"""Tool manager tests."""

from __future__ import annotations

from typing import Any

import pytest
from sage.core.engine import SageEngine
from sage.tools.builtin.core_tools import EchoTool
from sage.tools.interfaces import ToolManager, ToolResult
from sage.tools.manager import DefaultToolManager
from sage.tools.verification import ToolOutputVerifier


@pytest.mark.asyncio
async def test_calculator(engine: SageEngine) -> None:
    tm = engine.container.resolve(ToolManager)  # type: ignore[type-abstract]
    result = await tm.invoke("calculator", expression="(2 + 3) * 4")
    assert result.success
    assert result.output == 20


@pytest.mark.asyncio
async def test_echo(engine: SageEngine) -> None:
    tm = engine.container.resolve(ToolManager)  # type: ignore[type-abstract]
    result = await tm.invoke("echo", text="ping")
    assert result.success
    assert result.output == "ping"


class NullOutputTool:
    """Stub tool that succeeds with a None output (triggers the empty_output warning)."""

    name = "null_output"
    description = "succeeds with None output"

    def __init__(self) -> None:
        self.parameters_schema: dict[str, Any] = {}

    async def execute(self, **params: Any) -> ToolResult:
        return ToolResult(success=True, output=None)


class TestVerificationGate:
    """Tests for the Tool-R0 verification gate in DefaultToolManager.invoke()."""

    @pytest.fixture
    def clean_verifier(self) -> ToolOutputVerifier:
        return ToolOutputVerifier(strict=False)

    @pytest.fixture
    def strict_verifier(self) -> ToolOutputVerifier:
        return ToolOutputVerifier(strict=True)

    @pytest.fixture
    def raising_verifier(self) -> Any:
        class RaisingVerifier:
            async def verify(self, tool_name: str, result: ToolResult, *, expected_schema: dict[str, Any] | None = None):
                raise RuntimeError("verifier exploded")

        return RaisingVerifier()  # type: ignore[return-value]

    @pytest.mark.asyncio
    async def test_no_verifier_passthrough_unchanged(self) -> None:
        """verifier=None, result.metadata has no verification key."""
        manager = DefaultToolManager()
        manager.register(EchoTool())
        result = await manager.invoke("echo", text="ping")
        assert result.success
        assert "verification" not in result.metadata
        assert "verification_issues" not in result.metadata
        assert "verification_error" not in result.metadata

    @pytest.mark.asyncio
    async def test_clean_verification_populates_metadata(self, clean_verifier: ToolOutputVerifier) -> None:
        """Clean verification, metadata verification is populated."""
        manager = DefaultToolManager(verifier=clean_verifier)
        manager.register(EchoTool())
        result = await manager.invoke("echo", text="ping")
        assert result.success
        verification = result.metadata["verification"]
        assert verification["verified"] is True
        assert verification["confidence"] == 1.0
        assert verification["issue_count"] == 0
        assert "verification_issues" not in result.metadata
        assert "verification_error" not in result.metadata

    @pytest.mark.asyncio
    async def test_issues_serialized_into_metadata(self, strict_verifier: ToolOutputVerifier) -> None:
        """Verification issues, verification_issues is serialized with the four expected fields."""
        manager = DefaultToolManager(verifier=strict_verifier)
        manager.register(NullOutputTool())
        result = await manager.invoke("null_output")
        assert "verification" in result.metadata
        assert result.metadata["verification"]["verified"] is False
        assert result.metadata["verification"]["issue_count"] == 1
        issues = result.metadata["verification_issues"]
        assert len(issues) == 1
        issue = issues[0]
        assert set(issue) == {"severity", "category", "message", "field"}
        assert issue["severity"] == "warning"
        assert issue["category"] == "empty_output"
        assert "succeeded but returned no output" in issue["message"]
        assert issue["field"] is None

    @pytest.mark.asyncio
    async def test_raising_verifier_does_not_block_result(self, raising_verifier: Any) -> None:
        """verifier.verify raises, result is still returned with verification_error set."""
        manager = DefaultToolManager(verifier=raising_verifier)
        manager.register(EchoTool())
        result = await manager.invoke("echo", text="ping")
        assert result.success
        assert result.output == "ping"
        assert result.metadata["verification_error"] == "verifier exploded"

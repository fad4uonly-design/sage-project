"""Percent-of questions with numeric operands route to the calculator."""

import pytest
from sage.orchestrator.intent import IntentAnalyzer
from sage.orchestrator.models import IntentKind
from sage.tools.builtin.core_tools import CalculatorTool


@pytest.mark.parametrize(
    ("message", "expression"),
    [
        ("what is 15 percent of 240", "(15 * 240) / 100"),
        ("what is 15% of 240", "(15 * 240) / 100"),
        ("What's 15 % of 240?", "(15 * 240) / 100"),
        ("calculate 15% of 240", "(15 * 240) / 100"),
        ("15 percent of 240", "(15 * 240) / 100"),
        ("how much is 12.5 percent of 80", "(12.5 * 80) / 100"),
    ],
)
def test_percent_of_maps_to_calculator(message: str, expression: str) -> None:
    intent = IntentAnalyzer().analyze(message)

    assert intent.kind == IntentKind.TOOL
    assert intent.entities["tool"] == "calculator"
    assert intent.entities["args"] == {"expression": expression}
    assert intent.subject == expression


@pytest.mark.parametrize(
    "message",
    [
        "what is 15% of my budget",
        "what is 15 percent",
        "what is 15% of 240 plus tax",
    ],
)
def test_percent_without_numeric_operands_is_not_a_tool(message: str) -> None:
    assert IntentAnalyzer().analyze(message).kind != IntentKind.TOOL


async def test_percent_expression_evaluates_to_the_percentage() -> None:
    intent = IntentAnalyzer().analyze("what is 15 percent of 240")

    result = await CalculatorTool().execute(**intent.entities["args"])

    assert result.success
    assert result.output == 36

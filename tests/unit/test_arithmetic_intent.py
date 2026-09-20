"""Question-form arithmetic with numeric operands routes to the calculator."""

import pytest
from sage.orchestrator.intent import IntentAnalyzer
from sage.orchestrator.models import IntentKind
from sage.tools.builtin.core_tools import CalculatorTool


@pytest.mark.parametrize(
    ("message", "expression"),
    [
        ("what is 25 * 4", "25 * 4"),
        ("what is 25*4", "25 * 4"),
        ("what is 15 plus 30", "15 + 30"),
        ("What's 100 minus 42?", "100 - 42"),
        ("how much is 6 times 7", "6 * 7"),
        ("what is 84 divided by 4", "84 / 4"),
        ("what is 7 multiplied by 3", "7 * 3"),
        ("what is 12 / 25", "12 / 25"),
        ("what is 2.5 + 0.5", "2.5 + 0.5"),
        ("compute 3 plus 4 times 2", "3 + 4 * 2"),
        ("calculate 15 plus 30", "15 + 30"),
        ("what is 6 \u00f7 3", "6 / 3"),
    ],
)
def test_arithmetic_question_maps_to_calculator(message: str, expression: str) -> None:
    intent = IntentAnalyzer().analyze(message)

    assert intent.kind == IntentKind.TOOL
    assert intent.entities["tool"] == "calculator"
    assert intent.entities["args"] == {"expression": expression}
    assert intent.subject == expression


@pytest.mark.parametrize(
    ("message", "expression"),
    [
        ("calculate 2 ** 3", "2 ** 3"),
        ("calculate (2 + 3) * 4", "(2 + 3) * 4"),
    ],
)
def test_other_calculate_expressions_keep_the_verbatim_path(
    message: str, expression: str
) -> None:
    intent = IntentAnalyzer().analyze(message)

    assert intent.kind == IntentKind.TOOL
    assert intent.entities["args"] == {"expression": expression}


@pytest.mark.parametrize(
    "message",
    [
        "what is 12/25",
        "what is 2026-09-20",
        "what is 007 + 1",
        "what is 25",
        "what is 25 * 4 in binary",
    ],
)
def test_ambiguous_or_incomplete_arithmetic_is_not_a_tool(message: str) -> None:
    assert IntentAnalyzer().analyze(message).kind != IntentKind.TOOL


async def test_arithmetic_expression_evaluates() -> None:
    intent = IntentAnalyzer().analyze("what is 15 plus 30")

    result = await CalculatorTool().execute(**intent.entities["args"])

    assert result.success
    assert result.output == 45

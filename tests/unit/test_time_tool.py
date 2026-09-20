"""TimeTool reports local time with its UTC offset, not forced UTC."""

from datetime import datetime

from sage.tools.builtin.core_tools import TimeTool


async def test_current_time_reports_local_time_with_offset() -> None:
    """Regression: the tool used to return UTC ('...Z'), which is wrong for a
    user who is not on UTC."""
    result = await TimeTool().execute()

    assert result.success
    assert not result.output.endswith("Z")
    parsed = datetime.fromisoformat(result.output)
    assert parsed.utcoffset() == datetime.now().astimezone().utcoffset()

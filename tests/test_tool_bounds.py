from blazecode.tools.base import MAX_TOOL_CHARS, ToolResult, bound_result, bound_text


def test_bound_text_keeps_head_and_marks_truncation() -> None:
    text = "A" * 80_000
    clipped = bound_text(text, limit=1_000)
    assert len(clipped) < len(text)
    assert clipped.startswith("A" * 100)
    assert "truncated" in clipped
    assert clipped.endswith("A" * 10)


def test_bound_result_preserves_small_output() -> None:
    result = ToolResult("ok")
    assert bound_result(result) is result
    huge = ToolResult("x" * (MAX_TOOL_CHARS + 50), is_error=True)
    bounded = bound_result(huge)
    assert bounded is not huge
    assert bounded.is_error
    assert "truncated" in bounded.content

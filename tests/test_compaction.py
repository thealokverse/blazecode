from blazecode.context.compaction import compact_messages, estimate_tokens
from blazecode.session.message import Message


def test_compaction_keeps_system_and_recent_context() -> None:
    system = Message("system", "important system prompt")
    history = [
        Message("user", f"old question {index} " + "x" * 80)
        for index in range(20)
    ]
    history.append(Message("assistant", "latest answer"))
    compacted = compact_messages([system, *history], max_tokens=80, recent_messages=6)
    assert compacted[0] is system
    assert compacted[-1].content == "latest answer"
    assert len(compacted) < len(history) + 1


def test_compaction_does_not_start_with_orphan_tool_result() -> None:
    messages = [
        Message("system", "sys"),
        Message("assistant", tool_calls=[{"id": "1"}]),
        Message("tool", "large " + "x" * 400, tool_call_id="1"),
        Message("user", "current"),
    ]
    compacted = compact_messages(messages, max_tokens=20, recent_messages=3)
    assert compacted[0].role == "system"
    assert len(compacted) == 1 or compacted[1].role != "tool"
    assert estimate_tokens([]) == 0


def test_compaction_never_drops_oversized_current_task() -> None:
    system = Message("system", "sys")
    old = Message("user", "old")
    current = Message("user", "current " + "x" * 1000)
    compacted = compact_messages([system, old, current], max_tokens=10)
    assert compacted[0] is system
    assert current in compacted

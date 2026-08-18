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


def test_compaction_strips_unanswered_tool_calls() -> None:
    messages = [
        Message("system", "sys"),
        Message(
            "assistant",
            tool_calls=[
                {"id": "1", "type": "function", "function": {"name": "read"}},
                {"id": "2", "type": "function", "function": {"name": "write"}},
            ],
        ),
        Message("tool", "ok", tool_call_id="1", name="read"),
        Message("user", "continue"),
    ]
    compacted = compact_messages(messages, max_tokens=10_000)
    assistant = next(m for m in compacted if m.role == "assistant")
    assert [c["id"] for c in assistant.tool_calls] == ["1"]


def test_estimate_tokens_uses_latest_prompt_usage_not_sum() -> None:
    messages = [
        Message("user", "a"),
        Message("assistant", "b", input_tokens=1000, output_tokens=10),
        Message("user", "c"),
        Message("assistant", "d", input_tokens=1200, output_tokens=20),
    ]
    # must not sum both input_tokens (1000+1200); latest prompt wins
    assert estimate_tokens(messages) == 1220
    assert estimate_tokens(messages) < 2000


def test_compaction_inserts_note_when_history_is_trimmed() -> None:
    system = Message("system", "sys")
    history = [Message("user", f"old {index} " + "y" * 100) for index in range(12)]
    history.append(Message("user", "current task"))
    compacted = compact_messages([system, *history], max_tokens=60, recent_messages=4)
    assert compacted[0] is system
    notes = [m for m in compacted if m.role == "system" and m is not system]
    assert notes
    assert "compacted" in (notes[0].content or "")
    assert compacted[-1].content == "current task"


def test_compaction_summary_preserves_goal_and_changes() -> None:
    from blazecode.context.compaction import summarize_history

    messages = [
        Message("user", "Add a health endpoint"),
        Message("assistant", "I will add /health", tool_calls=[{"id": "1"}]),
        Message("tool", "Wrote app.py", tool_call_id="1", name="write"),
        Message("tool", "Error: tests failed", tool_call_id="2", name="bash"),
    ]
    summary = summarize_history(messages)
    assert "## Goal" in summary
    assert "health endpoint" in summary
    assert "## Changes" in summary
    assert "app.py" in summary
    assert "## Failures" in summary
    prior = summarize_history(
        [
            Message("system", "[context compacted]\n## Goal\nShip the endpoint"),
            Message("user", "continue"),
        ]
    )
    assert "## Decisions" in prior
    assert "context compacted" in prior



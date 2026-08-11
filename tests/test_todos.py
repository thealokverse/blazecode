from __future__ import annotations

from pathlib import Path

import pytest

from blazecode.agent.todos import TodoList, TodoStatus
from blazecode.tools.todo import TodoTool


def test_todo_list_replace_update_render() -> None:
    todos = TodoList()
    todos.replace(
        [
            ("inspect auth", "completed"),
            ("implement login", "in_progress"),
            ("add tests", "pending"),
        ]
    )
    rendered = todos.render()
    assert "✓ inspect auth" in rendered
    assert "◐ implement login" in rendered
    assert "○ add tests" in rendered
    todos.update("2", status="completed")
    todos.update("3", status="in_progress")
    assert todos.items[1].status is TodoStatus.COMPLETED
    assert todos.items[2].status is TodoStatus.IN_PROGRESS


@pytest.mark.asyncio
async def test_todo_tool_actions(tmp_path: Path) -> None:
    store = TodoList()
    tool = TodoTool(store)
    replaced = await tool.run(
        {
            "action": "replace",
            "items": [
                {"content": "one", "status": "pending"},
                {"content": "two", "status": "in_progress"},
            ],
        },
        tmp_path,
    )
    assert not replaced.is_error
    assert "one" in replaced.content
    listed = await tool.run({"action": "list"}, tmp_path)
    assert "two" in listed.content
    updated = await tool.run(
        {"action": "update", "id": "1", "status": "completed"}, tmp_path
    )
    assert not updated.is_error
    assert store.items[0].status is TodoStatus.COMPLETED


@pytest.mark.asyncio
async def test_todo_tool_rejects_multiple_in_progress(tmp_path: Path) -> None:
    tool = TodoTool(TodoList())
    result = await tool.run(
        {
            "action": "replace",
            "items": [
                {"content": "a", "status": "in_progress"},
                {"content": "b", "status": "in_progress"},
            ],
        },
        tmp_path,
    )
    assert result.is_error

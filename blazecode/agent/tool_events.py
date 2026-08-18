from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from blazecode.llm.client import ToolCallStart
from blazecode.mascot import State
from blazecode.permissions.approval import ApprovalManager
from blazecode.tools import TOOLS
from blazecode.tools.base import OutputCallback, Tool, ToolResult, bound_result
from blazecode.tools.todo import TodoTool

_ALIASES = {
    "read": "read",
    "write": "write",
    "edit": "edit",
    "bash": "bash",
    "grep": "grep",
    "todo": "todo",
    "todos": "todo",
    "shell": "bash",
    "run": "bash",
    "search": "grep",
    "str_replace": "edit",
    "strreplace": "edit",
}


def tool_call_message(call: ToolCallStart) -> dict[str, Any]:
    arguments = {
        key: value
        for key, value in call.arguments.items()
        if not str(key).startswith("_")
    }
    name = resolve_tool_name(call.name) or call.name
    function: dict[str, Any] = {
        "name": name,
        "arguments": json.dumps(arguments, ensure_ascii=False),
    }
    for key, value in call.function_extra.items():
        if key not in {"name", "arguments"}:
            function[key] = value
    payload: dict[str, Any] = {
        "id": call.call_id,
        "type": "function",
        "function": function,
    }
    for key, value in call.extra.items():
        if key not in {"id", "type", "function", "index"}:
            payload[key] = value
    return payload


def resolve_tool_name(name: str) -> str | None:
    raw = (name or "").strip()
    if raw in TOOLS:
        return raw
    lowered = raw.lower()
    if lowered in TOOLS:
        return lowered
    return _ALIASES.get(lowered)


def tool_state(tool: Tool) -> State:
    if tool.name in {"read", "grep"}:
        return State.SEARCHING
    if tool.name in {"write", "edit"}:
        return State.EDITING
    if tool.name == "todo":
        return State.THINKING
    return State.DEBUGGING


async def execute_tool(
    call: ToolCallStart,
    cwd: Path,
    approval: ApprovalManager,
    on_output: OutputCallback | None = None,
    todo_store: Any | None = None,
    trusted: bool = True,
) -> ToolResult:
    if call.arguments.get("_parse_error"):
        return ToolResult(
            f"Error: invalid tool arguments: {call.arguments['_parse_error']}",
            is_error=True,
        )
    resolved = resolve_tool_name(call.name)
    tool = TOOLS.get(resolved) if resolved else None
    if tool is None:
        return ToolResult(f"Error: unknown tool {call.name!r}", is_error=True)
    if tool.mutating and not trusted:
        return ToolResult(
            "Error: workspace is not trusted. Mutating tools are blocked. "
            "Trust this directory at startup to allow writes, edits, and shell commands.",
            is_error=True,
        )

    if tool.name == "todo" and todo_store is not None:
        tool = TodoTool(todo_store)
    approved, reason = await approval.approve_async(tool, call.arguments)
    if not approved:
        return ToolResult(f"Error: {reason}", is_error=True)
    try:
        result = await tool.run(call.arguments, cwd, on_output=on_output)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return ToolResult(f"Error: {exc}", is_error=True)
    return bound_result(result)


def interrupted_tool_message(call: ToolCallStart) -> dict[str, str | None]:
    return {
        "role": "tool",
        "content": "Error: interrupted before tool execution",
        "tool_call_id": call.call_id,
        "name": resolve_tool_name(call.name) or call.name,
    }

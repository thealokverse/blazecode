"""Small conversions between model tool calls and agent state."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from blazecode.llm.client import ToolCallStart
from blazecode.mascot import State
from blazecode.permissions.approval import ApprovalManager
from blazecode.tools import TOOLS
from blazecode.tools.base import Tool, ToolResult

_ALIASES = {
    "read": "read",
    "write": "write",
    "edit": "edit",
    "bash": "bash",
    "grep": "grep",
    "shell": "bash",
    "run": "bash",
    "search": "grep",
    "str_replace": "edit",
    "strreplace": "edit",
}


def tool_call_message(call: ToolCallStart) -> dict[str, Any]:
    """Serialize a streamed call for OpenAI-compatible history."""
    arguments = {
        key: value
        for key, value in call.arguments.items()
        if not str(key).startswith("_")
    }
    name = resolve_tool_name(call.name) or call.name
    return {
        "id": call.call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments, ensure_ascii=False),
        },
    }


def resolve_tool_name(name: str) -> str | None:
    """Map a model-emitted tool name onto the registry key, if any."""
    raw = (name or "").strip()
    if raw in TOOLS:
        return raw
    lowered = raw.lower()
    if lowered in TOOLS:
        return lowered
    return _ALIASES.get(lowered)


def tool_state(tool: Tool) -> State:
    """Map a tool to the corresponding Blaze activity state."""
    if tool.name in {"read", "grep"}:
        return State.SEARCHING
    if tool.name in {"write", "edit"}:
        return State.EDITING
    return State.DEBUGGING


async def execute_tool(
    call: ToolCallStart,
    cwd: Path,
    approval: ApprovalManager,
) -> ToolResult:
    """Run one tool call through approval and return its result."""
    if call.arguments.get("_parse_error"):
        return ToolResult(
            f"Error: invalid tool arguments: {call.arguments['_parse_error']}",
            is_error=True,
        )
    resolved = resolve_tool_name(call.name)
    tool = TOOLS.get(resolved) if resolved else None
    if tool is None:
        return ToolResult(f"Error: unknown tool {call.name!r}", is_error=True)
    approved, reason = approval.approve(tool, call.arguments)
    if not approved:
        return ToolResult(f"Error: {reason}", is_error=True)
    try:
        return await tool.run(call.arguments, cwd)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return ToolResult(f"Error: {exc}", is_error=True)


def interrupted_tool_message(call: ToolCallStart) -> dict[str, str | None]:
    """Build a tool-result payload for a call skipped by cancel."""
    return {
        "role": "tool",
        "content": "Error: interrupted before tool execution",
        "tool_call_id": call.call_id,
        "name": resolve_tool_name(call.name) or call.name,
    }

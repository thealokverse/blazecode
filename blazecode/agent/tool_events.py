"""Small conversions between model tool calls and agent state."""

from __future__ import annotations

import json
from typing import Any

from blazecode.llm.client import ToolCallStart
from blazecode.mascot import State
from blazecode.tools.base import Tool


def tool_call_message(call: ToolCallStart) -> dict[str, Any]:
    """Serialize a streamed call for OpenAI-compatible history."""
    return {
        "id": call.call_id,
        "type": "function",
        "function": {
            "name": call.name,
            "arguments": json.dumps(call.arguments, ensure_ascii=False),
        },
    }


def tool_state(tool: Tool) -> State:
    """Map a tool to the corresponding Blaze activity state."""
    if tool.name in {"read", "grep"}:
        return State.SEARCHING
    if tool.name in {"write", "edit"}:
        return State.EDITING
    return State.DEBUGGING


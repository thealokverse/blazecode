"""Event models the engine emits to the UI via an async queue."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class Event(BaseModel):
    """Common base. `type` is the discriminator."""

    type: str = "blaze"


class SessionInfo(Event):
    type: Literal["session_info"] = "session_info"
    session_id: str
    model: str
    provider: str


class TurnStarted(Event):
    type: Literal["turn_started"] = "turn_started"


class TextDelta(Event):
    type: Literal["text_delta"] = "text_delta"
    content: str


class ToolCallRequested(Event):
    type: Literal["tool_call_requested"] = "tool_call_requested"
    id: str
    name: str
    arguments: dict[str, Any] = {}


class ToolCallApprovalNeeded(Event):
    type: Literal["tool_call_approval_needed"] = "tool_call_approval_needed"
    id: str
    name: str
    arguments: dict[str, Any] = {}
    preview: str


class ToolResult(Event):
    type: Literal["tool_result"] = "tool_result"
    id: str
    name: str
    output: str
    error: bool = False


class TurnCompleted(Event):
    type: Literal["turn_completed"] = "turn_completed"
    usage: dict[str, Any] = {}


class Error(Event):
    type: Literal["error"] = "error"
    message: str
    recoverable: bool = True


__all__ = [
    "Event",
    "SessionInfo",
    "TurnStarted",
    "TextDelta",
    "ToolCallRequested",
    "ToolCallApprovalNeeded",
    "ToolResult",
    "TurnCompleted",
    "Error",
]

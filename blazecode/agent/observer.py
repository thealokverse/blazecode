"""UI-neutral observer interface for agent events."""

from __future__ import annotations

from typing import Any, Protocol

from blazecode.mascot import State
from blazecode.tools.base import ToolResult


class Observer(Protocol):
    """Callbacks implemented by terminal or embedded frontends."""

    def on_response_start(self) -> None:
        """Prepare to display a new model response."""

    def on_state(self, state: State) -> None:
        """Display a state transition."""

    def on_text(self, text: str) -> None:
        """Display an incremental text delta."""

    def on_tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        """Display a tool invocation."""

    def on_tool_result(self, name: str, result: ToolResult) -> None:
        """Display a completed tool result."""

    def on_error(self, message: str) -> None:
        """Display an unrecoverable error."""

    def on_complete(self) -> None:
        """Finalize rendering for a turn."""


class NullObserver:
    """No-op observer useful for tests and embedded use."""

    def on_response_start(self) -> None:
        """Do nothing."""

    def on_state(self, state: State) -> None:
        """Do nothing."""

    def on_text(self, text: str) -> None:
        """Do nothing."""

    def on_tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        """Do nothing."""

    def on_tool_result(self, name: str, result: ToolResult) -> None:
        """Do nothing."""

    def on_error(self, message: str) -> None:
        """Do nothing."""

    def on_complete(self) -> None:
        """Do nothing."""


from __future__ import annotations

from typing import Any, Protocol

from blazecode.mascot import State
from blazecode.tools.base import ToolResult


class Observer(Protocol):
    def on_response_start(self) -> None: ...

    def on_state(self, state: State) -> None: ...

    def on_text(self, text: str) -> None: ...

    def on_tool_call(self, name: str, arguments: dict[str, Any]) -> None: ...

    def on_tool_output(self, name: str, chunk: str) -> None: ...

    def on_tool_result(self, name: str, result: ToolResult) -> None: ...

    def on_error(self, message: str) -> None: ...

    def on_notice(self, message: str) -> None: ...

    def on_complete(self) -> None: ...

    def on_todos(self, todos: Any) -> None: ...


class NullObserver:
    def on_response_start(self) -> None:
        pass

    def on_state(self, state: State) -> None:
        pass

    def on_text(self, text: str) -> None:
        pass

    def on_tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        pass

    def on_tool_output(self, name: str, chunk: str) -> None:
        pass

    def on_tool_result(self, name: str, result: ToolResult) -> None:
        pass

    def on_error(self, message: str) -> None:
        pass

    def on_notice(self, message: str) -> None:
        pass

    def on_complete(self) -> None:
        pass

    def on_todos(self, todos: Any) -> None:
        pass

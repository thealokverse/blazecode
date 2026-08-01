from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from blazecode import __version__
from blazecode.mascot import FACES, Mascot, State, blaze
from blazecode.tools.base import ToolResult
from blazecode.ui.theme import ACCENT, ERROR, MUTED, SUCCESS

_STATUS: dict[State, str] = {
    State.THINKING: "thinking...",
    State.SEARCHING: "searching...",
    State.EDITING: "writing...",
    State.DEBUGGING: "working...",
}


class Renderer:
    def __init__(
        self,
        console: Console | None = None,
        mascot: Mascot = blaze,
        *,
        interactive: bool = True,
    ) -> None:
        self.console = console or Console()
        self.mascot = mascot
        self.interactive = interactive
        self._live: Live | None = None
        self._activity: str | None = None
        self._line_open = False
        self._tool_target = ""

    def on_response_start(self) -> None:
        self._activity = _STATUS.get(State.THINKING)
        self._start_live()

    def on_state(self, state: State) -> None:
        if state in _STATUS:
            self._activity = _STATUS[state]
            self._start_live()
        self._refresh_live()

    def on_text(self, text: str) -> None:
        self._stop_live()
        self._activity = None
        if not text:
            return
        self.console.print(Text(text), end="", soft_wrap=True)
        self._line_open = not text.endswith("\n")
        self._flush()

    def on_tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        self._tool_target = _tool_target(name, arguments)
        self._refresh_live()

    def on_tool_result(self, name: str, result: ToolResult) -> None:
        self._stop_live()
        self._activity = None
        if not self.interactive:
            return
        self._finish_line()
        summary = _tool_summary(name)
        target = self._tool_target
        self._tool_target = ""
        suffix = f" {target}" if target else ""
        if result.is_error:
            self.console.print(f"  ↳ {summary}{suffix} failed", style=ERROR)
        else:
            self.console.print(f"  ↳ {summary}{suffix}", style=MUTED)

    def on_error(self, message: str) -> None:
        self._stop_live()
        self._activity = None
        self._finish_line()
        self.console.print(message, style=ERROR)

    def on_complete(self) -> None:
        self._stop_live()
        self._activity = None
        self._finish_line()
        if not self.interactive:
            return
        if self.mascot.state == State.SUCCESS:
            self.console.print(f"blaze {self.mascot.face}", style=SUCCESS)
        elif self.mascot.state == State.ERROR:
            self.console.print(f"blaze {self.mascot.face}", style=ERROR)
        else:
            return
        self.console.print()

    def approve(self, name: str, arguments: dict[str, Any]) -> bool:
        # sync approver for standalone use. repl uses the async prompt toolkit path.
        from rich.prompt import Confirm

        target = _tool_target(name, arguments)
        self._stop_live()
        try:
            return Confirm.ask(
                f"Run [bold]{target}[/bold]?",
                default=False,
                console=self.console,
            )
        finally:
            self._start_live()

    def pause_activity(self) -> None:
        self._stop_live()

    def resume_activity(self) -> None:
        self._start_live()

    @staticmethod
    def tool_target(name: str, arguments: dict[str, Any]) -> str:
        return _tool_target(name, arguments)

    def _renderable(self) -> Text:
        status = self._activity or "…"
        return Text(f"{self.mascot.face} {status}", style=ACCENT)

    def _start_live(self) -> None:
        if not self.interactive or self._live:
            return
        self._live = Live(
            self._renderable(),
            console=self.console,
            refresh_per_second=12,
            transient=True,
        )
        self._live.start()

    def _refresh_live(self) -> None:
        if self._live:
            self._live.update(self._renderable(), refresh=True)

    def _finish_line(self) -> None:
        if self._line_open:
            self.console.print()
            self._line_open = False

    def _stop_live(self) -> None:
        if self._live:
            try:
                self._live.stop()
            except Exception:
                pass
            self._live = None

    def _flush(self) -> None:
        try:
            file = getattr(self.console, "file", None) or sys.stdout
            flush = getattr(file, "flush", None)
            if callable(flush):
                flush()
        except Exception:
            pass


def render_header(console: Console, model: str, cwd: Path) -> None:
    home = Path.home().resolve()
    resolved = cwd.resolve()
    if resolved == home:
        directory = "~"
    else:
        try:
            directory = "~/" + str(resolved.relative_to(home))
        except ValueError:
            directory = str(resolved)

    face = FACES[State.THINKING]
    body = Text()
    body.append(f"{face} Blazecode (v{__version__})\n\n", style="bold")
    body.append("model:     ", style=MUTED)
    body.append(f"{model}", style=ACCENT)
    body.append("   /models to change\n", style=MUTED)
    body.append("directory: ", style=MUTED)
    body.append(directory, style=ACCENT)
    console.print(
        Panel(
            body,
            border_style=ACCENT,
            padding=(0, 1),
            expand=False,
        )
    )
    console.print()


def _tool_target(name: str, arguments: dict[str, Any]) -> str:
    for key in ("path", "command"):
        value = arguments.get(key)
        if isinstance(value, str):
            return _safe_terminal_text(value, 120)
    try:
        safe = {
            key: ("…" if key in {"content", "new_string", "old_string"} else value)
            for key, value in arguments.items()
            if not str(key).startswith("_")
        }
        return json.dumps(safe, ensure_ascii=False, default=str)[:120]
    except (TypeError, ValueError):
        return "{…}"


def _safe_terminal_text(value: str, limit: int) -> str:
    rendered = "".join(
        character if character.isprintable() else repr(character)[1:-1]
        for character in value
    )
    return rendered if len(rendered) <= limit else rendered[: limit - 3] + "…"


def _tool_summary(name: str) -> str:
    return {
        "read": "Read",
        "grep": "Searched",
        "write": "Wrote",
        "edit": "Edited",
        "bash": "Ran",
    }.get(name, name.capitalize())

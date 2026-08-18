from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from blazecode import __version__
from blazecode.mascot import FACES, Mascot, State, blaze
from blazecode.permissions.trust import display_path
from blazecode.tools.base import ToolResult
from blazecode.ui.markdown import render_diff, render_markdown, render_partial, split_stable
from blazecode.ui.theme import ACCENT, ERROR, MUTED, SUCCESS

_STATUS: dict[State, str] = {
    State.THINKING: "thinking",
    State.SEARCHING: "searching",
    State.EDITING: "writing",
    State.DEBUGGING: "working",
}

_TOOL_GERUND = {
    "read": "reading",
    "grep": "searching",
    "write": "writing",
    "edit": "editing",
    "bash": "running",
    "todo": "updating todos",
}


class _LiveView:
    def __init__(self, renderer: Renderer) -> None:
        self._renderer = renderer

    def __rich__(self) -> Group | Text:
        return self._renderer._renderable()


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
        self._buffer = ""
        self._committed = 0
        self._pending = ""
        self._tool_output_open = False
        self._tool_line_start = True

    def on_response_start(self) -> None:
        self._reset_stream()
        self._activity = _STATUS.get(State.THINKING)
        self._start_live()

    def on_state(self, state: State) -> None:
        if state in _STATUS:
            self._activity = _STATUS[state]
            self._start_live()
        self._refresh_live()

    def on_text(self, text: str) -> None:
        if not text:
            return
        self._activity = None
        if not self.interactive:
            self._stop_live()
            self.console.print(Text(text), end="", soft_wrap=True)
            self._line_open = not text.endswith("\n")
            self._flush()
            return
        self._buffer += text
        self._paint_stream()

    def on_tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        self._flush_stream()
        self._tool_target = _tool_target(name, arguments)
        self._tool_output_open = False
        self._tool_line_start = True
        verb = _TOOL_GERUND.get(name, name)
        target = self._tool_target
        self._activity = f"{verb} {target}".rstrip() if target else verb
        self._start_live()
        self._refresh_live()

    def on_tool_output(self, name: str, chunk: str) -> None:
        if not chunk or not self.interactive:
            return
        self._stop_live()
        self._activity = None
        if not self._tool_output_open:
            self._finish_line()
            label = _tool_summary(name)
            target = self._tool_target
            suffix = f" {target}" if target else ""
            self.console.print(f"  ↳ {label}{suffix}", style=MUTED)
            self._tool_output_open = True
            self._tool_line_start = True
        # indent each physical line once; keep mid-line chunks intact
        for line in chunk.splitlines(keepends=True):
            if self._tool_line_start:
                self.console.print("    ", style=MUTED, end="")
                self._tool_line_start = False
            if line.endswith("\n"):
                self.console.print(line[:-1], style=MUTED)
                self._tool_line_start = True
                self._line_open = False
            else:
                self.console.print(line, style=MUTED, end="")
                self._line_open = True
        self._flush()

    def on_tool_result(self, name: str, result: ToolResult) -> None:
        self._flush_stream()
        self._stop_live()
        self._activity = None
        if not self.interactive:
            self._tool_output_open = False
            self._tool_line_start = True
            return
        self._finish_line()
        if not self._tool_output_open:
            summary = _tool_summary(name)
            target = self._tool_target
            suffix = f" {target}" if target else ""
            if result.is_error:
                self.console.print(f"  ↳ {summary}{suffix} failed", style=ERROR)
            else:
                self.console.print(f"  ↳ {summary}{suffix}", style=MUTED)
        elif result.is_error:
            self.console.print("    failed", style=ERROR)
        self._tool_target = ""
        self._tool_output_open = False
        self._tool_line_start = True
        if result.diff and not result.is_error:
            self.console.print(render_diff(result.diff.rstrip("\n")))
            self.console.print()

    def on_error(self, message: str) -> None:
        self._flush_stream()
        self._stop_live()
        self._activity = None
        self._finish_line()
        self.console.print(message, style=ERROR)

    def on_notice(self, message: str) -> None:
        self._flush_stream()
        self._stop_live()
        self._finish_line()
        self.console.print(f"  · {message}", style=MUTED)

    def on_complete(self) -> None:
        self._flush_stream()
        self._stop_live()
        self._activity = None
        self._finish_line()
        self._reset_stream()
        if not self.interactive:
            return
        if self.mascot.state == State.SUCCESS:
            self.console.print(f"blaze {self.mascot.face}", style=SUCCESS)
        elif self.mascot.state == State.ERROR:
            self.console.print(f"blaze {self.mascot.face}", style=ERROR)
        else:
            return
        self.console.print()

    def pause_activity(self) -> None:
        self._stop_live()

    def resume_activity(self) -> None:
        self._start_live()

    @staticmethod
    def tool_target(name: str, arguments: dict[str, Any]) -> str:
        return _tool_target(name, arguments)

    def on_todos(self, todos: Any) -> None:
        rendered = getattr(todos, "render", lambda: "")()
        if not rendered or not self.interactive:
            return
        self._flush_stream()
        self._stop_live()
        self._finish_line()
        self.console.print(rendered, style=MUTED)
        self.console.print()

    def _reset_stream(self) -> None:
        self._buffer = ""
        self._committed = 0
        self._pending = ""

    def _paint_stream(self) -> None:
        stable, pending = split_stable(self._buffer, self._committed)
        if stable:
            self._stop_live()
            self._print_stable(stable)
            self._committed += len(stable)
        self._pending = pending
        if pending or self._activity:
            self._start_live()
            self._refresh_live()
        else:
            self._stop_live()

    def _flush_stream(self) -> None:
        if not self.interactive:
            return
        remainder = self._buffer[self._committed :]
        if remainder:
            self._stop_live()
            self._print_stable(remainder)
            self._committed = len(self._buffer)
        self._pending = ""
        self._stop_live()

    def _print_stable(self, text: str) -> None:
        if not text:
            return
        self._finish_line()
        # avoid a blank Rich line when the segment is only newlines
        if text.strip():
            self.console.print(render_markdown(text))
        elif text.endswith("\n"):
            self.console.print()
        self._line_open = False
        self._flush()

    def _renderable(self) -> Group | Text:
        # live stays one/two lines only; never full code panels
        if self._activity:
            face_line = Text(f"{self.mascot.face} {_pulse(self._activity)}", style=ACCENT)
        else:
            face_line = Text(f"{self.mascot.face} …", style=ACCENT)
        if self._pending and not self._activity:
            return Group(render_partial(self._pending), face_line)
        return face_line

    def _start_live(self) -> None:
        if not self.interactive or self._live or not self.console.is_terminal:
            return
        self._live = Live(
            _LiveView(self),
            console=self.console,
            refresh_per_second=8,
            transient=True,
            vertical_overflow="crop",
        )
        self._live.start()

    def _refresh_live(self) -> None:
        if self._live:
            self._live.refresh()

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


def render_header(
    console: Console,
    model: str,
    cwd: Path,
    *,
    git_line: str = "",
    trusted: bool | None = None,
    provider: str = "",
) -> None:
    face = FACES[State.THINKING]
    shown = f"{provider} / {model}" if provider else model
    body = Text()
    body.append(f"{face} Blazecode (v{__version__})\n\n", style="bold")
    body.append("model:     ", style=MUTED)
    body.append(shown, style=ACCENT)
    body.append("   /models to change\n", style=MUTED)
    body.append("directory: ", style=MUTED)
    body.append(display_path(cwd), style=ACCENT)
    if git_line:
        body.append("\ngit:       ", style=MUTED)
        body.append(git_line, style=ACCENT)
    if trusted is False:
        body.append("\ntrust:     ", style=MUTED)
        body.append("untrusted", style=ERROR)
    console.print(
        Panel(
            body,
            border_style=ACCENT,
            padding=(0, 1),
            expand=False,
        )
    )
    console.print()


def render_status(
    console: Console,
    *,
    session: str,
    provider: str,
    model: str,
    approval: str,
    workspace: str,
    tokens: int,
    state: str,
    face: str,
    git_line: str = "",
    todos: str = "",
) -> None:
    rows = [
        ("session", session),
        ("provider", provider),
        ("model", model),
        ("approval", approval),
        ("workspace", workspace),
        ("tokens", f"{tokens:,}"),
        ("blaze", f"{state} {face}"),
    ]
    if git_line:
        rows.insert(5, ("git", git_line))
    for label, value in rows:
        line = Text()
        line.append(f"  {label:<10}", style=MUTED)
        style = ERROR if label == "workspace" and value == "untrusted" else ACCENT
        line.append(value, style=style)
        console.print(line)
    if todos:
        console.print()
        console.print(todos, style=MUTED)



def _pulse(label: str) -> str:
    frame = 1 + int(time.monotonic() * 3) % 3
    return f"{label}{'.' * frame}"


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
        "todo": "Todos",
    }.get(name, name.capitalize())
